import os
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

URL = "https://termine.essen.de/?link=4ce9"

# Service to book (text of the button on step 1)
SERVICE_NAME = "Anmeldung"

# Selectors from the Essen website
SERVICE_BUTTON_SELECTOR = ".activity-selectable-item"
WIZARD_NEXT_SELECTOR = "#next-button"
NEXT_DATE_SELECTOR = "#next-date-button"
DATE_SELECTOR = "#date-select"
TIME_SELECTOR = "#time-select"

NTFY_TOPIC = os.environ.get("NTFY_TOPIC")


def notify(message):
    """Send notification to iPhone through ntfy."""
    if not NTFY_TOPIC:
        print("ERROR: NTFY_TOPIC is not configured.")
        return

    response = requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers={
            "Title": "Essen Termin verfügbar!",
            "Priority": "urgent",
            "Tags": "calendar,rotating_light",
        },
        timeout=20,
    )
    response.raise_for_status()
    print("iPhone notification sent.")


def dump_page(page, label):
    """Print what the page currently shows, for debugging."""
    print(f"\n===== DEBUG: {label} =====")
    print("PAGE URL:", page.url)
    print("PAGE TITLE:", page.title())
    print("BODY TEXT:", page.inner_text("body")[:2000])
    print("--- CONTROLS ON PAGE (calendar day buttons hidden) ---")
    controls = page.evaluate(
        """
        () => Array.from(
            document.querySelectorAll(
                'button:not(.duet-date__day), input, select, a, [role=button]'
            )
        ).map(e => e.outerHTML.slice(0, 300))
        """
    )
    for c in controls[:60]:
        print(c)
    print("--- END CONTROLS ---")
    try:
        page.screenshot(path="error.png", full_page=True)
    except Exception:
        pass


def get_date(page):
    """Read the current date from #date-select (empty if none available)."""
    return page.locator(DATE_SELECTOR).input_value().strip()


def get_available_times(page):
    """Read the times from #time-select (empty list if disabled/empty)."""
    time_select = page.locator(TIME_SELECTOR)

    if time_select.is_disabled():
        return []

    times = []
    for option in time_select.locator("option").all():
        value = option.get_attribute("value")
        text = option.inner_text().strip()

        # Ignore the empty "Zeit wählen" option.
        if value and text:
            times.append(text)

    return times


def wait_for_page(page):
    """Wait until the date picker page is ready."""
    page.locator(DATE_SELECTOR).wait_for(state="visible", timeout=30000)
    page.locator(NEXT_DATE_SELECTOR).wait_for(state="visible", timeout=30000)
    page.locator(TIME_SELECTOR).wait_for(state="attached", timeout=30000)

    # Allow the JavaScript application to finish updating.
    page.wait_for_timeout(2000)


def open_date_step(page):
    """
    Get to the date picker (wizard step 3).

    The site may start at step 1 (choose the service) or resume directly at
    the date step, so wait for whichever appears first.
    """
    try:
        page.locator(f"{SERVICE_BUTTON_SELECTOR}, {DATE_SELECTOR}").first.wait_for(
            state="visible", timeout=30000
        )

        if page.locator(DATE_SELECTOR).is_visible():
            print("Already on the date step.")
        else:
            service = page.locator(
                SERVICE_BUTTON_SELECTOR, has_text=SERVICE_NAME
            ).first
            print(f"Selecting service: {SERVICE_NAME}")
            service.click(timeout=15000)

            for step in range(6):
                page.wait_for_timeout(1500)

                if page.locator(DATE_SELECTOR).is_visible():
                    break

                print(f"Wizard step {step + 1}: clicking Weiter...")
                page.locator(WIZARD_NEXT_SELECTOR).click(timeout=15000)

        wait_for_page(page)

    except PlaywrightTimeoutError:
        dump_page(page, "could not reach the date step")
        raise


def check_dates(page):
    """One check: go to the date step, click the arrow, see if a date appears."""
    print("Opening Essen appointment page...")

    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    open_date_step(page)

    # Date field already filled -> a date is available.
    current_date = get_date(page)
    print(f"Date field: {current_date or '(empty - Wählen Sie ein Datum)'}")

    if not current_date:
        # Click the arrow next to "Wählen Sie ein Datum".
        print("Clicking the next-date arrow...")
        page.locator(NEXT_DATE_SELECTOR).click()

        try:
            # If a date is available, the field changes from empty to that date.
            page.wait_for_function(
                """
                () => {
                    const element = document.querySelector('#date-select');
                    return element && element.value && element.value.trim() !== '';
                }
                """,
                timeout=10000,
            )
        except PlaywrightTimeoutError:
            print("The date field stayed empty -> no available date.")
            return None, []

        current_date = get_date(page)
        print(f"Date field now: {current_date}")

        # Give the website a moment to fill the time selector.
        page.wait_for_timeout(2500)

    times = get_available_times(page)
    if not times:
        times = ["(Uhrzeit bitte auf der Seite prüfen)"]

    print("\n" + "=" * 50)
    print("APPOINTMENT FOUND!")
    print("=" * 50)
    print(f"Date : {current_date}")
    print(f"Times: {', '.join(times)}")
    print("=" * 50)
    return current_date, times


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            viewport={"width": 1440, "height": 1000},
            locale="de-DE",
        )

        try:
            date, times = check_dates(page)

            if date and times:
                message = (
                    "🚨 TERMIN VERFÜGBAR!\n\n"
                    f"Datum: {date}\n"
                    f"Uhrzeit: {', '.join(times)}\n\n"
                    f"Jetzt buchen:\n{URL}"
                )
                notify(message)

                # Save screenshot for debugging.
                page.screenshot(path="appointment-found.png", full_page=True)
                print("\nMonitoring stopped.")
            else:
                print("\nNo appointment found.")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
