import os
import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

URL = "https://termine.essen.de/?link=4ce9"

# Confirmed selectors from the Essen website
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


def get_date(page):
    """Read the current date from #date-select."""
    return page.locator(DATE_SELECTOR).input_value()


def get_available_times(page):
    """
    Check #time-select.

    The website disables this select when no appointment
    time is available.
    """
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
    """Wait until the appointment page is ready."""
    try:
        page.locator(DATE_SELECTOR).wait_for(state="visible", timeout=30000)
        page.locator(NEXT_DATE_SELECTOR).wait_for(state="visible", timeout=30000)
        page.locator(TIME_SELECTOR).wait_for(state="attached", timeout=30000)
    except PlaywrightTimeoutError:
        print("PAGE URL:", page.url)
        print("PAGE TITLE:", page.title())
        print("BODY TEXT:", page.inner_text("body")[:2000])
        print("FRAMES:", [f.url for f in page.frames])
        page.screenshot(path="error.png", full_page=True)
        raise

    # Allow the JavaScript application to finish updating.
    page.wait_for_timeout(2000)


def check_dates(page):
    print("Opening Essen appointment page...")

    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    wait_for_page(page)

    current_date = get_date(page)
    print(f"Starting date: {current_date}")

    # First check the currently displayed date.
    times = get_available_times(page)
    if times:
        print("Appointment already available!")
        return current_date, times

    # Check successive available dates.
    for attempt in range(20):
        old_date = get_date(page)

        print(f"\nChecking next date (attempt {attempt + 1}/20)...")
        print(f"Current date: {old_date}")

        # Click the confirmed next-date button.
        page.locator(NEXT_DATE_SELECTOR).click()

        try:
            # Wait until #date-select actually changes.
            page.wait_for_function(
                """
                oldDate => {
                    const element = document.querySelector('#date-select');
                    return element &&
                           element.value &&
                           element.value !== oldDate;
                }
                """,
                arg=old_date,
                timeout=15000,
            )
        except PlaywrightTimeoutError:
            print("The date did not change.")
            print("Refreshing page...")
            page.reload(wait_until="domcontentloaded", timeout=60000)
            wait_for_page(page)
            continue

        new_date = get_date(page)
        print(f"New date: {new_date}")

        # Give the website time to populate the time selector.
        page.wait_for_timeout(1500)

        times = get_available_times(page)
        if times:
            print("\n" + "=" * 50)
            print("APPOINTMENT FOUND!")
            print("=" * 50)
            print(f"Date : {new_date}")
            print(f"Times: {', '.join(times)}")
            print("=" * 50)
            return new_date, times

        print("No available time on this date.")

    print("\nReached maximum number of dates.")
    return None, []


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
