from flask import Flask, Response, redirect, request
import os
import requests
import re
import urllib.parse
import logging
from bs4 import BeautifulSoup
import html

# Set up basic logging
logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)

@app.route('/rss')
def get_rss_feed():
    try:
        rss_feed_url = 'https://rss-bridge.org/bridge01/?action=display&bridge=YoutubeBridge&context=By+custom+name&custom=LinusTechTips&duration_min=&duration_max=&format=Atom'
        
        logging.info(f"Fetching RSS feed from {rss_feed_url}")
        response = requests.get(rss_feed_url)

        if response.status_code != 200:
            logging.error(f"Failed to fetch RSS feed with status code: {response.status_code}")
            return Response('Failed to fetch RSS feed', status=500, content_type='text/plain')

        feed_content = response.content
        soup = BeautifulSoup(feed_content, 'html.parser')


        button_style = "padding:5px 10px; background-color:#007bff; color:white; text-decoration:none; border-radius:5px;"

        # Modify each entry to include styled "more" and "less" links within the content
        for entry in soup.find_all('entry'):
            content = entry.find('content')
            if content:
                # Construct the styled "more" and "less" links as escaped HTML
                more_link_html = f'&lt;a href="{os.environ.get("HOSTNAME", "localhost")}/track_click/more/{entry.id.text}" style="{button_style}"&gt;More&lt;/a&gt;'
                less_link_html = f'&lt;a href="{os.environ.get("HOSTNAME", "localhost")}/track_click/less/{entry.id.text}" style="{button_style}"&gt;Less&lt;/a&gt;'

                # Append links to the content
                content.string = content.text + '<br/>' + html.unescape(more_link_html) + '<br/><br/>' + html.unescape(less_link_html) + '<br/>'

        modified_feed_content = str(soup)

        return Response(modified_feed_content, content_type='application/atom+xml')
    except Exception as e:
        logging.exception("An error occurred while processing the RSS feed:")
        return Response(f'An error occurred: {str(e)}', status=500, content_type='text/plain')



@app.route('/track_click/<action>/<item_id>')
def track_click(action, item_id):
    if action not in ['more', 'less']:
        return Response('Invalid action', status=400, content_type='text/plain')

    # Log the click action
    logging.info(f"Clicked '{action}' on item {item_id}")

    # Here you can add code to increment counters in a database, if you prefer

    # Redirect to a page or perform another action as needed
    return Response(f"You clicked '{action}' on item {item_id}", content_type='text/plain')


@app.route('/redirect')
def redirect_to_original():
    url = request.args.get('url')
    if url:
        return redirect(urllib.parse.unquote(url))
    else:
        return Response('No URL provided', status=400, content_type='text/plain')


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)