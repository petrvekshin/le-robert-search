import os
from pathlib import Path
import requests
import concurrent.futures
from collections import Counter, defaultdict
from bs4 import BeautifulSoup
from progressbar import progressbar


HTML_PATH = './html/'
AUDIO_PATH = './audio/'


def execute_async(function, sequence, executor_type='thread', batch_size=64, max_workers=None, *args, **kwargs):
    """Asynchronously execute a function that takes an argument from a sequence and args and/or kwargs optionally. 
    """
    results = []
    for i in progressbar(range(0, len(sequence), batch_size)):
        current_items = sequence[i:i+batch_size]
        if executor_type == 'process':
            with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(function, item, *args, **kwargs) for item in current_items]
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(function, item, *args, **kwargs) for item in current_items]
        for ft in futures:
            results.append(ft.result())
    return results


def download_html(word_path):
    """Download HTML of a definition page ending in word_path (word).
    """
    response = requests.get(f'https://dictionnaire.lerobert.com/definition/{word_path}')
    status_code = response.status_code
    if status_code != 200:
        return {'word_path': word_path, 'status_code': status_code, 'def_exists': False}
    content = response.text
    soup = BeautifulSoup(content, 'lxml')
    response_word_path = response.url.split('/')[-1] # if redirected
    filename_path = Path(HTML_PATH) / Path(f'{response_word_path}.html')
    definitions = find_definitions(soup)
    if not definitions:
        return {'word_path': word_path, 'status_code': status_code, 'def_exists': False}
    with open(filename_path, 'w', encoding='utf-8') as f:
        f.write(content)
    return {'word_path': word_path, 'status_code': status_code, 'def_exists': True}


def read_html_file(filename):
    """Read a saved version of HTML using filename (word_path) and return a soup object.
    """
    filename_path = Path(HTML_PATH) / Path(f'{filename}.html')
    with open(filename_path, 'r', encoding='utf-8') as f:
        content = ''.join(f.readlines())
    return BeautifulSoup(content, 'lxml')


def download_audio(html_filename):
    """Download all audio files found in the definition section of an HTML file.
    """
    soup = read_html_file(html_filename)
    definitions = find_definitions(soup)
    
    src_prefix = '/medias/SOUNDS/originals/mp3/'
    url_prefix = 'https://dictionnaire.lerobert.com'
    
    audio_sources = []
    for definition in definitions:
        audio_sources.extend([audio for audio in definition.find_all('source', recursive=True)])

    if not audio_sources:
        return html_filename, False
    
    audio_links = set()
    for s in audio_sources:
        audio_links.add(s['src'])

    for audio_link in audio_links:
        if (len(audio_link) > len(src_prefix)) and (audio_link[:len(src_prefix)] == src_prefix):
            filename = audio_link[len(src_prefix):]
        else:
            filename = audio_link.replace('/', '_')
        filename_path = Path(AUDIO_PATH)  / Path(filename)
        if os.path.isfile(filename_path):
            continue
            
        url = url_prefix + audio_link
        response = requests.get(url)
        with open(filename_path, 'wb') as f:
            f.write(response.content)
            
    return html_filename, True


def list_html_files():
    """Return a list of saved HTML files (filenames without extensions).
    """
    return [item[:-5] for item in os.listdir(HTML_PATH)]


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

    
def find_word_paths_html_file(filename):
    """Find all definition links on a page and return their word_paths.
    """
    soup = read_html_file(filename)
    links = soup.find_all('a')
    word_paths = set()
    for a in links:
        try:
            if (len(a['href']) > 12) and (a['href'][:12] == '/definition/'):
                word_paths.add(a['href'][12:])
        except:
            pass
    return word_paths    
    
    
def is_valid_html_file(filename):
    """File is valid if it contains definitions and was saved using the word_path as its name.
    """
    soup = read_html_file(filename)
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
        section_div = BeautifulSoup(content, 'lxml').find('section', class_='def').div
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


def tag_parent_counter(filename):
    """Find all tags with their parents up to <div class='b'>.
    """
    cnt = Counter()
    definitions = find_definitions(read_html_file(filename))
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


def index_strings_by_parents(filename):
    """Using parents as keys, return indices needed to locate a string with such parents.
    """
    definitions = find_definitions(read_html_file(filename))
    parents = defaultdict(lambda: defaultdict(lambda: []))
    for def_ind, def_tag in enumerate(definitions):
        strings = locate_strings(def_tag)
        for string in strings:
            parents[string['parents']][def_ind].append(string['indices'])
    for key in parents:
        parents[key] = dict(parents[key])
    return filename, dict(parents)