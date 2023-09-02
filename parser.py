import os
from pathlib import Path
import requests
import concurrent.futures
from collections import Counter, defaultdict
from bs4 import BeautifulSoup
from progressbar import progressbar


def execute_async(function, sequence, processes=False, batch_size=64, max_workers=None, *args, **kwargs):
    """Asynchronously execute a function that takes an argument from a sequence and args and/or kwargs optionally. 
    """
    results = []
    for i in progressbar(range(0, len(sequence), batch_size)):
        current_items = sequence[i:i+batch_size]
        if processes:
            with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(function, item, *args, **kwargs) for item in current_items]
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(function, item, *args, **kwargs) for item in current_items]
        for ft in futures:
            results.append(ft.result())
    return results


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


def read_html_file(filename, html_path='./assets/html/original/'):
    """Read a saved version of HTML using filename (word_path) and return a soup object.
    """
    filename_path = Path(html_path) / Path(f'{filename}.html')
    with open(filename_path, 'r', encoding='utf-8') as f:
        content = ''.join(f.readlines())
    return BeautifulSoup(content, 'html.parser')


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


def list_html_files(html_path='./assets/html/original/'):
    """Return a list of saved HTML files (filenames without extensions).
    """
    return [item[:-5] for item in os.listdir(html_path)]


def find_definitions(soup):
    """Find 'Définition de ...' tags: <div class='b'>.
    """
    main_tag = soup.body.find('div', class_='ws-c', recursive=False).main
    section_with_definitions = main_tag.find('section', class_='def', recursive=False)
    definitions = section_with_definitions.find_all('div', class_='b', recursive=False)
    return definitions


def find_orig_word_path(soup):
    """Find the word_path of a saved page later.
    """
    try:
        return soup.find('meta', {'property': "og:url"})['content'].split('/')[-1]
    except:
        return None

    
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
    
    
def is_valid_html_file(filename, html_path='./assets/html/original/'):
    """File is valid if it contains definitions and was saved using the word_path as its name.
    """
    soup = read_html_file(filename, html_path=html_path)
    definitions = find_definitions(soup)
    if definitions and (filename == find_orig_word_path(soup)):
        return filename, True
    return filename, False


def get_suggested_word_paths(search_term):
    """Search for definition pages using built-in search.
    """
    url = f'https://dictionnaire.lerobert.com/autocomplete.json?t=gui&q={search_term}'
    suggestions = json.loads(requests.get(url).text)
    return set(item['page'][12:] for item in suggestions if item['type'] == 'def')


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


def name_and_class(tag):
    """Return name and class of a tag as strings.
    """
    try:
        # inside <div class="b"> all tags contain no more than one class
        classes = ' '.join(tag['class'])
    except:
        classes = None
    return tag.name, classes


def tag_parent_counter(filename, html_path='./assets/html/original/'):
    """Find all tags with their parents up to <div class='b'>.
    """
    cnt = Counter()
    definitions = find_definitions(read_html_file(filename, html_path=html_path))
    for def_tag in definitions:
        cnt.update([find_all_parents(t)  for t in def_tag.find_all()])
    return cnt


def get_content(tag, indices):
    """Get content by indices: tag.content[ind_0].content[ind_1]...
    """
    res = tag
    for ind in indices:
        res = res.contents[ind]
    return res


def locate_strings(tag):
    """Find all strings except '\n' in a tag and return them along with their parents and content indices.
    """
    strings = []
    for string in tag.find_all(string=True):
        if string == '\n':
            continue
        tag_iter = string
        parents = []
        indices = []
        indices.append(len(list(tag_iter.previous_siblings)))
        while True:
            tag_iter = tag_iter.parent
            name, classes = name_and_class(tag_iter)
            if tag_iter == tag:
                break
            parents.append((name, classes))
            indices.append(len(list(tag_iter.previous_siblings)))
        strings.append({'string': string, 'parents': tuple(parents[::-1]), 'indices': tuple(indices[::-1])})

    return strings


def index_strings_by_parents(filename, html_path='./assets/html/original/'):
    """Using parents as keys, return indices needed to locate a string with such parents.
    """
    definitions = find_definitions(read_html_file(filename, html_path=html_path))
    parents = defaultdict(lambda: defaultdict(lambda: []))
    for def_ind, def_tag in enumerate(definitions):
        strings = locate_strings(def_tag)
        for string in strings:
            parents[string['parents']][def_ind].append(string['indices'])
    for key in parents:
        parents[key] = dict(parents[key])
    return filename, dict(parents)