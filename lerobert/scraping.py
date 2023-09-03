import os
from pathlib import Path
import requests
import json
from bs4 import BeautifulSoup

from lerobert.processing import execute_async, read_html_file, find_definitions


def get_explored_links():
    """Return all definition links found in "Explorer le dictionnaire" section.
    """
    links = []
    page_ids = []
    
    def get_links_on_page(page_id, get_last_page_number=False):
        content = requests.get(f'https://dictionnaire.lerobert.com/explore/def/{page_id}').text
        section_div = BeautifulSoup(content, 'html.parser').find('section', class_='def').div
        if get_last_page_number:
            last_page = section_div.find('div', class_='p', recursive=False).find_all('a', recursive=False)[-1].text
        else:
            last_page = None
        links_on_page = section_div.find('div', class_='l-l', recursive=False).find_all('a', recursive=False)
        return {'page_id': page_id, 'links': links_on_page, 'last_page': last_page}
    
    # parsing first pages
    first_chars = '0ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    results = execute_async(get_links_on_page, first_chars, get_last_page_number=True)
    for res in results:
        links.extend(res['links'])
        for num in range(2, int(res['last_page'])+1):
            page_ids.append(f"{res['page_id']}/{num}")
    
    # parsing remaining pages
    results = execute_async(get_links_on_page, page_ids)
    for res in results:
        links.extend(res['links'])
    
    return links


def get_suggested_word_paths(search_term):
    """Search for definition pages using built-in search.
    """
    url = f'https://dictionnaire.lerobert.com/autocomplete.json?t=gui&q={search_term}'
    suggestions = json.loads(requests.get(url).text)
    return set(item['page'][12:] for item in suggestions if item['type'] == 'def')


def download_html(word_path, html_path='./assets/html/original/', rewrite=False):
    """Download HTML of a definition page ending in word_path (word).
    """
    if os.path.isfile(Path(html_path) / Path(f'{word_path}.html')) and not rewrite:
        return {'word_path': word_path, 'status_code': None, 'def_exists': True}
    
    response = requests.get(f'https://dictionnaire.lerobert.com/definition/{word_path}')
    status_code = response.status_code
    if status_code != 200:
        return {'word_path': word_path, 'status_code': status_code, 'def_exists': False}
    content = response.text
    soup = BeautifulSoup(content, 'html.parser')
    definitions = find_definitions(soup)
    if not definitions:
        return {'word_path': word_path, 'status_code': status_code, 'def_exists': False}
    response_word_path = response.url.split('/')[-1] # if redirected
    filename_path = Path(html_path) / Path(f'{response_word_path}.html')
    os.makedirs(html_path, exist_ok=True)
    with open(filename_path, 'w', encoding='utf-8') as f:
        f.write(content)
    return {'word_path': word_path, 'status_code': status_code, 'def_exists': True}


def download_media(html_filename, 
                   audio=True,
                   images=True,
                   html_path='./assets/html/original/', 
                   audio_path='./assets/audio/', 
                   image_path='./assets/images/thumbnails/'):
    """Download all media files of specified type found in the definition section of an HTML file.
    """
    if not (audio or images):
        return
    
    soup = read_html_file(html_filename, html_path=html_path)
    definitions = find_definitions(soup)
    url_prefix = 'https://dictionnaire.lerobert.com'
    
    def download_src(media_path, src_prefix, tag):
        os.makedirs(media_path, exist_ok=True)
        links = set()
        for definition in definitions:
            links.update([t['src'] for t in definition.find_all(tag, recursive=True)])
        for link in links:
            if link.startswith(src_prefix):
                filename = link[len(src_prefix):]
            else:
                filename = link.replace('/', '_')
            filename_path = Path(media_path)  / Path(filename)
            if os.path.isfile(filename_path):
                continue
            response = requests.get(url_prefix + link)
            with open(filename_path, 'wb') as f:
                f.write(response.content)
    
    if audio:
        download_src(audio_path, '/medias/SOUNDS/originals/mp3/', 'source')

    if images:
        download_src(image_path, '/medias/IMAGES/originals/thumbnails/', 'img')

    return

    
def find_word_paths_html_file(filename, html_path='./assets/html/original/'):
    """Find all definition links on a page and return their word_paths.
    """
    soup = read_html_file(filename, html_path=html_path)
    links = soup.find_all('a')
    word_paths = set()
    for a in links:
        try:
            if (len(a['href']) > 12) and (a['href'][:12] == '/definition/'):
                word_paths.add(a['href'][12:])
        except:
            pass
    return word_paths    
    