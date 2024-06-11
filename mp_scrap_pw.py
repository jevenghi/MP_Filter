import re
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError
import ignore_lists
from utils import (
    check_artist,
    proxies,
    tg_send_mp,
    block_media,
    check_connection,
    connection_failed
)
import time, schedule, datetime, random
from config import mp_logger, user_agents
import os
from typing import List
from os import strerror
import importlib
from dotenv import load_dotenv
load_dotenv()

proxy_server = os.getenv('PROXY_SERVER')
proxy_pass = os.getenv('PROXY_PASS')

other_genres = ["vinyl-dance-en-house", "vinyl-singles", "vinyl-jazz-en-blues", "vinyl-wereldmuziek"]
initial_timestamp = os.path.getmtime("ignore_lists.py")

genres = [
    "vinyl-pop", "vinyl-hardrock-en-metal", "vinyl-overige-vinyl", "vinyl-rock",
    "vinyl-filmmuziek-en-soundtracks", "vinyl-r-b-en-soul",  "cassettebandjes"

]

def links_file_updater(txt_file: str, new_links: List[str], limit: int) -> None:
    """
    Append new links to a text file and limit the file to a specified number of lines.

    Args:
        txt_file (str): The path to the text file to be updated.
        new_links (List[str]): A list of strings representing new links to be appended to the file.
        limit (int): The maximum number of lines to keep in the file. If the file exceeds
            this limit, older lines will be removed.

    Returns:
        None
    """
    try:
        with open(txt_file, "a+") as file:
            for link in new_links:
                file.write(f'{link}\n')

            file.seek(0)
            lines = file.readlines()

            if len(lines) > limit:
                keep_lines = lines[-limit:]
            else:
                keep_lines = lines
            file.seek(0)
            file.truncate()
            file.writelines(keep_lines)

    except (OSError, IOError) as e:
        tg_send_mp(f"An error occurred while updating the links file: {e}")
    except Exception as e:
        tg_send_mp(f"An unexpected error occurred while updating the links file: {e}")


def press_cookies_button(page, username):
    if connection_failed(page, "https://www.marktplaats.nl/l/cd-s-en-dvd-s", mp_logger):
        mp_logger.info(username)
        return False
    try:
        page.locator(".gdpr-consent-modal").get_by_role("button").first.click(timeout=5000)
    except PlaywrightTimeoutError:
        # page.frame_locator("#sp_message_iframe_918358").get_by_role("button", name='Accepteren').click()
        iframe_id_pattern = re.compile(r'#sp_message_iframe_(\d+)')
        iframe_id_match = iframe_id_pattern.search(page.content())

        if iframe_id_match:
            iframe_id = iframe_id_match.group(1)
            iframe_locator = f'#sp_message_iframe_{iframe_id}'
            try:
                page.frame_locator(iframe_locator).get_by_role("button", name='Accepteren').click()
            except Exception as e:
                mp_logger.critical(f"Cookies accept failed. Error {e}")
                return False

        else:
            mp_logger.critical("Couldn't find the iframe ID.")
            return False

    return True


def mp_scrap():
    tg_send_mp("Scrape started")
    new_links = []
    reload_ignore_lists()

    with sync_playwright() as p:
        username = random.choice(proxies).split(":")[2]
        browser = p.chromium.launch(
            # timeout=60000,
            # headless=False,
            proxy={
                'server': f'{proxy_server}',
                'username': username,
                'password': proxy_pass
            },

        )
        try:
            with open("entries.txt", "r") as file:
                existing_links = set(line.strip() for line in file)
        except OSError as error:
            mp_logger.critical(strerror(error.errno))
            return

        with browser.new_page(user_agent=random.choice(user_agents)) as page:
            # if connection_failed(page, "https://www.marktplaats.nl/l/cd-s-en-dvd-s", mp_logger):
            #     mp_logger.info(username)
            #     return

            if not press_cookies_button(page, username):
                return

            for genre in genres:

                for i in range(1, 5):
                    delay = random.randint(2000, 4000)
                    page.wait_for_timeout(delay)
                    start_time = time.time()

                    page.route("**/*", block_media)
                    if connection_failed(page, f"https://www.marktplaats.nl/l/cd-s-en-dvd-s/{genre}/p/{i}/", mp_logger):
                        mp_logger.info(username)
                        links_file_updater("entries.txt", new_links, 3000)
                        return

                    listings = page.query_selector_all(".hz-Listing.hz-Listing--list-item")

                    for listing in listings:
                        try:
                            delay = random.randint(0, 1000)
                            page.wait_for_timeout(delay)
                            listing.hover()
                            seller = listing.query_selector(".hz-Listing-seller-name").text_content()

                            if seller not in ignore_lists.ignore_sellers:
                                desc = listing.query_selector(".hz-Listing-title").text_content()

                                if check_artist(desc, ignore_lists.ignore_artists):
                                    ad_id_pattern = r'(?<=[/a|/m])\d+(?=-)'
                                    link = "https://www.marktplaats.nl" + listing.query_selector(
                                        ".hz-Listing-coverLink").get_attribute("href")
                                    try:
                                        ad_id = re.search(ad_id_pattern, link).group(0)
                                    except Exception as e:
                                        mp_logger.warning(f'{e} occured while trying to extract ad id in link {link}')
                                        continue

                                    if ad_id not in existing_links:
                                        hyperlink = f'<a href="{link}">LINK</a>'
                                        message_text = f'{hyperlink} // {desc} // {seller} // page {i}'
                                        new_links.append(ad_id)
                                        tg_send_mp(message_text)

                        except Exception as e:
                            timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
                            # page.screenshot(path=f"mp_screens/{timestamp}.png")
                            mp_logger.info(username)
                            mp_logger.warning(f"Error occurred: {e}")
                            break

                    end_time = time.time()
                    iteration_time = end_time - start_time
                    if iteration_time > 50:
                        mp_logger.warning(f"{genre} / page {i} time elapsed: {iteration_time:.2f} seconds. "
                                          f"Proxy {username}")

    links_file_updater("entries.txt", new_links, 3000)

    tg_send_mp("scrape complete")


def reload_ignore_lists():
    global initial_timestamp
    current_timestamp = os.path.getmtime("ignore_lists.py")
    if current_timestamp > initial_timestamp:
        importlib.reload(ignore_lists)
        mp_logger.info(
            f"Change detected. Ignore sellers len {len(ignore_lists.ignore_sellers)}, "
            f"ignore artists len {len(ignore_lists.ignore_artists)}")

        initial_timestamp = current_timestamp


schedule.every(30).minutes.do(mp_scrap)

while True:
   now = datetime.datetime.now().time()
   if datetime.time(7, 30) <= now <= datetime.time(23, 59, 59):
     schedule.run_pending()
     time.sleep(60)

# mp_scrap()

