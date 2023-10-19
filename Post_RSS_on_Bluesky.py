from atproto import Client, models
import asyncio
import argparse
import requests
import feedparser
import io
import html
import datetime
import logging
import os
from logging.handlers import RotatingFileHandler

LOG = logging.getLogger('bot')
LOG_PATTERN = logging.Formatter('%(asctime)s:%(levelname)s: [%(filename)s] %(message)s')

def setuplogger():

    conf_filename = None

    steam_handler = logging.StreamHandler()
    steam_handler.setFormatter(LOG_PATTERN)
    steam_handler.setLevel(logging.DEBUG)

    def setup_logger(logger_name, file_name=None, add_steam=False):
        file_name = file_name or logger_name
        log_filename = f"{file_name}.log"

        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.DEBUG)
        file_handler = RotatingFileHandler(log_filename, "a", 1000000, 1)
        file_handler.setFormatter(LOG_PATTERN)
        logger.addHandler(file_handler)
        if add_steam:
            logger.addHandler(steam_handler)

    setup_logger("bot", conf_filename, True)

def clamp_text(text, max_length, length_url):
    """
    Clamp the text to a specified number of characters, ensuring that whole words are kept intact.
    If the text is truncated, "..." is appended at the end.

    :param text: The input text to be clamped.
    :param max_length: The maximum number of characters for the clamped text.
    :return: The clamped text.
    """

    # Calculate the space needed for the "..." and the URL.
    reserved_length = 3 + length_url

    # If the text is already shorter than or equal to the max length, return it as is.
    if len(text) + length_url <= max_length:
        return text + "\n"

    # Subtract the reserved length from the max length to determine how much space we have for the text.
    truncated_text = text[:max_length - reserved_length]

    # Find the last space to ensure we don't cut off in the middle of a word.
    last_space_index = truncated_text.rfind(" ")

    # If no space is found, it means the first word itself is longer than max_length - 3.
    # In this case, we'll truncate the word and add "...".
    if last_space_index == -1:
        return truncated_text + "...\n"

    # Return the truncated text up to the last space, followed by "..."
    return text[:last_space_index] + "...\n"

class RSSfeed():
    def __init__(self, url, last_post):
        self.url = url
        self.last_post = last_post

class BlueSkyTask:
    def __init__(self, login, password, feed):
        self.feed = feed
        self.client = Client()
        self.client.login(login, password)

    async def periodic_task(self):
        while True:
            html_text = requests.get(self.feed.url).text
            newsFeed = feedparser.parse(html_text)
            new_posts = [entry for entry in newsFeed.entries if datetime.datetime.strptime(entry.published, '%a, %d %b %Y %H:%M:%S %z') > self.feed.last_post]

            for post in new_posts:
                linkURL = post["link"]
                title = post["title"]
                ftext = ""
                images = []
                
                if "media_content" in post:
                    for media in post["media_content"]:
                        r = requests.get(media["url"])
                        buf = io.BytesIO(r.content)

                        # uploading images
                        try:
                            upload = self.client.com.atproto.repo.upload_blob(buf)
                            # sadly we don't have alt text
                            images.append(models.AppBskyEmbedImages.Image(alt='Img alt', image=upload.blob))
                        except:
                            LOG.exception("Fatal Error uploading image to BS")

                if "links" in post:
                    for link in post["links"]:

                        if link["type"] == "image/jpg":
                            imgUrl = link["href"]
                            r = requests.get(imgUrl)
                            buf = io.BytesIO(r.content)
                            upload = self.client.com.atproto.repo.upload_blob(buf)
                            images.append(models.AppBskyEmbedImages.Image(alt='Image de la news', image=upload.blob))

                embed = models.AppBskyEmbedImages.Main(images=images)

                if "summary" in post:
                    ftext = html.unescape(post["summary"])
                
                # clamping the new to 300 characters, 34 is the space taken by the URL (whatever it is)            
                newSummary = clamp_text(title + "\n\n" + ftext, 300, 34)

                # URL link in title
                facets = []

                LOG.info("Posting " + title)
                
                facets.append(models.AppBskyRichtextFacet.Main(
                            features=[models.AppBskyRichtextFacet.Link(uri=linkURL)],
                            index=models.AppBskyRichtextFacet.ByteSlice(byte_start=0, byte_end=len(title.encode('UTF-8'))),))


                self.client.com.atproto.repo.create_record(
                    models.ComAtprotoRepoCreateRecord.Data(
                        repo=self.client.me.did,
                        collection=models.ids.AppBskyFeedPost,
                        record=models.AppBskyFeedPost.Main(created_at=self.client.get_current_time_iso(), text=newSummary, facets=facets, embed=embed),
                    )
                )



            if new_posts:
                self.feed.last_post = datetime.datetime.strptime(new_posts[0].published, '%a, %d %b %Y %H:%M:%S %z')
            with open("last_scan_date.txt", "w") as f:
                f.write(self.feed.last_post.strftime('%a, %d %b %Y %H:%M:%S %z'))


            await asyncio.sleep(60)



async def main(login, password, feed_url):

    setuplogger()

    if os.path.exists("last_scan_date.txt"):
        with open("last_scan_date.txt", "r") as f:
            last_post_date = datetime.datetime.strptime(f.read().strip(), '%a, %d %b %Y %H:%M:%S %z')
    else:
        last_post_date = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)

    feed = RSSfeed(feed_url, last_post_date)
    task = BlueSkyTask(login, password, feed)

    await task.periodic_task()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a periodic task with login and password.")
    parser.add_argument("login", type=str, help="Login for the task.")
    parser.add_argument("password", type=str, help="Password for the task.")
    parser.add_argument("feed_url", type=str, help="URL of the RSS feed to scan.")
    args = parser.parse_args()

    asyncio.run(main(args.login, args.password, args.feed_url))
