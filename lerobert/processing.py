import os
from pathlib import Path
import concurrent.futures
import re
from itertools import accumulate
from collections import defaultdict
from tqdm import tqdm
from bs4 import BeautifulSoup

from lerobert.embedding import tag_text


def execute_async(function, sequence, processes=False, batch_size=64, max_workers=None, *args, **kwargs):
    """Asynchronously execute a function that takes an argument from a sequence and args and/or kwargs optionally. 
    """
    results = []
    for i in tqdm(range(0, len(sequence), batch_size)):
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


def list_html_files(html_path='./assets/html/original/'):
    """Return a list of saved HTML files (filenames without extensions).
    """
    return [item[:-5] for item in os.listdir(html_path)]


def read_html_file(filename, html_path='./assets/html/original/'):
    """Read a saved version of HTML using filename (word_path) and return a soup object.
    """
    filename_path = Path(html_path) / Path(f'{filename}.html')
    with open(filename_path, 'r', encoding='utf-8') as f:
        content = ''.join(f.readlines())
    return BeautifulSoup(content, 'html.parser')


def find_definitions(soup):
    """Find 'Définition de ...' tags: <div class='b'>.
    """
    main_tag = soup.body.find('div', class_='ws-c', recursive=False).main
    section_with_definitions = main_tag.find('section', class_='def', recursive=False)
    definitions = section_with_definitions.find_all('div', class_='b', recursive=False)
    return definitions


def check_html_file(filename, html_path='./assets/html/original/'):
    """Check if an HTML file contains definitions and was saved using the word_path as its name.
    """
    soup = read_html_file(filename, html_path=html_path)
    definitions_found = (len(find_definitions(soup)) > 0)
    try:
        orig_word_path = soup.find('meta', {'property': "og:url"})['content'].split('/')[-1]
    except:
        orig_word_path = ''
    correct_name = (filename == orig_word_path)

    return filename, definitions_found, correct_name


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
            name = tag_iter.name
            try:
                # inside <div class="b"> all tags contain no more than one class
                classes = ' '.join(tag_iter['class'])
            except:
                classes = None
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


def wrap_words(html_string, tagger, words=None, lemmas=None):
    """Wrap words and/or lemmas in <span class="word"></span>.
    """
    word_set = set(words) if words else set()
    lemma_set = set(lemmas) if lemmas else set()
    if not (word_set or lemma_set):
        return html_string
    # html_string is expected to be a tag, 
    # i.e. html_string[0] = '<' and html_string[-1] = '>'
    html_tag_inds = [0]
    html_tags = []
    strings = []
    re_html_str = re.compile(r'(?<=>)[^><]+(?=<)')
    for t in re_html_str.finditer(html_string):
        strings.append(t.group())
        html_tag_inds.extend(t.span())
        html_tags.append(html_string[html_tag_inds[-3]:html_tag_inds[-2]])
    html_tags.append(html_string[html_tag_inds[-1]:])
    text_string = ''.join(strings)
    string_lens = [len(s) for s in strings]
    string_acc_lens = [a for a in accumulate([len(s) for s in strings])]
    text_tags = tag_text(text_string, tagger)
    
    text_tag_inds = [[] for _ in range(len(strings))]
    text_ind_start = cur_string_ind = 0
    for tag in text_tags:
        if (tag['word'].lower() in word_set) or (tag['lemma'].lower() in lemma_set):
            tag_ind_start = text_string[text_ind_start:].index(tag['word'])
            tag_ind_end = tag_ind_start + len(tag['word'])
            while tag_ind_start >= string_acc_lens[cur_string_ind]:
                cur_string_ind += 1
            # tag shouldn't span two strings
            if tag_ind_end <= string_acc_lens[cur_string_ind]:
                string_ind_start = string_acc_lens[cur_string_ind] - string_lens[cur_string_ind]
                text_tag_inds[cur_string_ind].append((tag_ind_start - string_ind_start, 
                                                      tag_ind_end - string_ind_start))
    strings_with_tags = []
    for ind, string in enumerate(strings):
        strings_with_tags.append([])
        ind_start = 0
        for tag_inds in text_tag_inds[ind]:
            sub_string = string[ind_start:tag_inds[0]]
            if sub_string:
                strings_with_tags[ind].append((sub_string, False))
            strings_with_tags[ind].append((string[tag_inds[0]:tag_inds[1]], True))
            ind_start = tag_inds[1]
        sub_string = string[ind_start:]
        if sub_string:
            strings_with_tags[ind].append((string[ind_start:], False))

    updated_strings = []
    for string_items in strings_with_tags:
        string = ''
        for item in string_items:
            if item[1]:
                string += f'<span class="word">{item[0]}</span>'
            else:
                string += item[0]
        updated_strings.append(string)

    updated_html_string = html_tags[0]
    for string, html_tag in zip(updated_strings, html_tags[1:]):
        updated_html_string += string + html_tag
    
    return updated_html_string
