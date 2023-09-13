import os
from pathlib import Path
import concurrent.futures
import re
from collections import defaultdict
from tqdm import tqdm
from bs4 import BeautifulSoup
import torch



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
    try:
        # original HTML
        main_tag = soup.body.find('div', class_='ws-c', recursive=False).main
        section_with_definitions = main_tag.find('section', class_='def', recursive=False)
        return section_with_definitions.find_all('div', class_='b', recursive=False)
    except AttributeError:
        # processed HTML
        return soup.find_all('div', class_='b', recursive=False)


def get_definition_header_data(definition_tag):
    """Get words and parts of speech after 'Définition de'.
    """
    strings = [t for t in definition_tag.h3.contents if t.name == None]
    words = []
    for string in strings:
        for term in string.split(','):
            for word in term.split(' '):
                word_stripped = word.strip(', \n')
                if word_stripped and ((word_stripped[0] != '(') or (word_stripped[-1] != ')')):
                    words.append(word_stripped)
    cats = definition_tag.h3.find_all('span', class_='d_cat', recursive=True)
    # print(cats)
    categories = [t.text.strip(', \n') for cat in cats for t in cat if t.name == None]
    return {'words': words, 'categories': categories}


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


# TAGGING WORDS
def tag_text(text, tagger):
    """Tag text and return a list of dictionaries containing 'word', 'pos', and 'lemma'.
    """
    tags = []
    for t in tagger.tag_text(text):
        word, pos, lemma = t.split('\t')
        tags.append({'word': word, 'pos': pos, 'lemma': lemma})
    return tags


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
    string_lens = [len(s) for s in strings]
    acc_sum = 0
    string_acc_lens = []
    for string in strings:
        acc_sum += len(string)
        string_acc_lens.append(acc_sum)
    # we want to use the whole string for tagging
    text_string = ''.join(strings)
    text_tags = tag_text(text_string, tagger)
    text_tag_inds = [[] for _ in range(len(strings))]
    text_ind_start = 0
    cur_string_ind = 0
    string = strings[cur_string_ind]
    for tag in text_tags:
        tag_ind_start = text_string.find(tag['word'], text_ind_start)
        if tag_ind_start == -1:
            continue
        tag_ind_end = tag_ind_start + len(tag['word'])
        text_ind_start = tag_ind_end
        # find the string index where the tag starts
        while tag_ind_start >= string_acc_lens[cur_string_ind]:
            cur_string_ind += 1
        # lemma of "l'" can be "la|le" 
        tag_lemmas = set(tag['lemma'].lower().split('|'))
        # beside being in a set of words or lemmas, the tag also shouldn't span two strings
        if (((tag['word'].lower() in word_set) or tag_lemmas.intersection(lemma_set))
            and (tag_ind_end <= string_acc_lens[cur_string_ind])):
            string_ind_start = string_acc_lens[cur_string_ind] - string_lens[cur_string_ind]
            text_tag_inds[cur_string_ind].append((tag_ind_start - string_ind_start, 
                                                  tag_ind_end - string_ind_start))
    strings_with_tags = []
    for ind, string in enumerate(strings):
        strings_with_tags.append([])
        ind_start = 0
        for tag_ind_start, tag_ind_end in text_tag_inds[ind]:
            sub_string = string[ind_start:tag_ind_start]
            if sub_string:
                strings_with_tags[ind].append((sub_string, False))
            strings_with_tags[ind].append((string[tag_ind_start:tag_ind_end], True))
            ind_start = tag_ind_end
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


def process_html(filename,
                 tagger,
                 orig_html_path='./assets/html/original/',
                 proc_html_path='./assets/html/processed/'):
    """Process original HTML files for their use locally.
    """
    processed_definitions = []
    soup = read_html_file(filename, html_path=orig_html_path)
    def_tags = find_definitions(soup)
    # we're going to treat header words as both "words" and "lemmas" when tagging text
    example_ind_start = 0
    num_examples = 0
    # filename_stripped = filename.replace('-', '_')
    filename_stripped = filename
    for def_tag in def_tags:
        words = get_definition_header_data(def_tag)['words']
        example_tags = def_tag.find_all(True, class_='d_xpl')
        num_examples += len(example_tags)
        for example_ind, example_tag in enumerate(example_tags, start=example_ind_start):
            updated_example = wrap_words(str(example_tag), tagger, words=words, lemmas=words)
            updated_example_tag = BeautifulSoup(updated_example, 'html.parser')
            updated_example_tag = updated_example_tag.find(True, class_='d_xpl')
            updated_example_tag['id'] = f'{filename_stripped}_{example_ind}'
            example_tag.replace_with(updated_example_tag)
        example_ind_start += len(example_tags)
        links = def_tag.find_all('a')
        for link in links:
            try:
                if link['href'][0] == '/':
                    link['href'] = 'https://dictionnaire.lerobert.com' + link['href']
                    link['target'] = '_blank'
                    link['rel'] = 'noopener noreferrer'
            except:
                continue
        processed_definitions.append(str(def_tag))
    os.makedirs(proc_html_path, exist_ok=True)
    processed_definitions = '\n'.join(processed_definitions)
    processed_definitions = processed_definitions.replace('/medias/SOUNDS/originals/mp3', '/audio')
    processed_definitions = processed_definitions.replace('/medias/IMAGES/originals/thumbnails', '/image-thumbnails')
    with open(proc_html_path + filename + '.html', 'w', encoding='utf-8') as f:
        f.write(processed_definitions)

        
def map_words(word_path, html_path='./assets/html/processed/'):
    """Map words found in the header of each definition to their word_paths and additional information.
    """
    word_map = defaultdict(lambda: defaultdict(lambda: []))
    soup = read_html_file(word_path, html_path=html_path)
    def_tags = find_definitions(soup)
    example_ind_start = 0
    for def_ind, def_tag in enumerate(def_tags):
        words = get_definition_header_data(def_tag)['words']
        example_tags = def_tag.find_all(True, class_='d_xpl')
        if example_tags:
            example_ind_start = int(example_tags[0]['id'].split('_')[-1])
        def_example_inds = [def_ind, example_ind_start, len(example_tags)]
        example_ind_start += len(example_tags)
        for word in words:
            word_map[word.lower()][word_path].append(def_example_inds)
            
    return word_map


# EMBEDDINGS
def compute_embeddings_html_tag(html_tag, tokenizer, model):
    """Compute embeddings of the strings inside <span class='word'></span> tags.
    'html_tag' is expected to be of the class='d_xpl' (example).
    """
    tokens = []
    mask = [False]
    # whole_string = html_tag.text
    strings = html_tag.find_all(string=True)
    for string in strings:
        string_tokens = tokenizer(string.lower(), return_tensors='pt')['input_ids'][0][1:-1]
        if string_tokens.shape[0] > 0:
            tokens.append(string_tokens)
            try:
                string_mask = ['word' in string.parent['class']]*string_tokens.shape[0]
            except KeyError:
                string_mask = [False]*string_tokens.shape[0]
            mask.extend(string_mask)
    mask.append(False)
    special_tokens = tokenizer('', return_tensors='pt')['input_ids'][0]
    tokens = torch.cat([special_tokens[:1], *tokens, special_tokens[1:]])
    tokens = tokens.reshape(1, len(mask))
    with torch.no_grad():
        model_output = model(input_ids=tokens)

    return torch.mean(model_output[0][0][mask, :], 0)


def compute_embeddings_html_file(filename, tokenizer, model, embedding_path, html_path='./assets/html/processed'):
    """Compute and save embeddings for 'example' (class='d_xpl') tags in an HTML file. 
    """
    def_tags = find_definitions(read_html_file(filename, html_path=html_path))
    example_tags = []
    for def_tag in def_tags:
        for example_tag in def_tag.find_all(True, class_='d_xpl'):
            example_tags.append(example_tag)
    example_embeddings = []
    for ind, example_tag in enumerate(example_tags):
        assert int(example_tag['id'].split('_')[-1]) == ind
        example_embeddings.append(compute_embeddings_html_tag(example_tag, tokenizer, model))
    if not example_embeddings:
        return
    torch.save(torch.stack(example_embeddings, dim=0), Path(embedding_path) / Path(f'{filename}.pt'))


def compute_embeddings_selected_text(payload, tokenizer, model, max_length=510):
    """Compute contextual embeddings for the selected text. 
    """
    text_before = payload.text[:payload.selection_start]
    text_selected = payload.text[payload.selection_start:payload.selection_end]
    text_after = payload.text[payload.selection_end:]
    
    tokens_selected = tokenizer(text_selected.lower(), return_tensors='pt')['input_ids'][0][1:-1]
    len_selected = tokens_selected.shape[0]
    lim_side = int((max_length - len_selected) / 2)
    
    len_before = 0
    word_tokens_before = []
    for word in text_before.split(' ')[::-1]:
        word_tokens = tokenizer(word.lower(), return_tensors='pt')['input_ids'][0][1:-1]
        if len_before + word_tokens.shape[0] > lim_side:
            break
        if word_tokens.shape[0] > 0:
            word_tokens_before.append(word_tokens)
            len_before += word_tokens.shape[0]
    word_tokens_before = word_tokens_before[::-1]
    
    len_after = 0
    word_tokens_after = []
    for word in text_after.split(' '):
        word_tokens = tokenizer(word.lower(), return_tensors='pt')['input_ids'][0][1:-1]
        if len_after + word_tokens.shape[0] > lim_side:
            break
        if word_tokens.shape[0] > 0:
            word_tokens_after.append(word_tokens)
            len_after += word_tokens.shape[0]
    
    mask = [*[False]*(len_before+1), *[True]*len_selected, *[False]*(len_after+1)]
    special_tokens = tokenizer('', return_tensors='pt')['input_ids'][0]
    tokens = torch.cat([special_tokens[:1], 
                        *word_tokens_before, 
                        tokens_selected, 
                        *word_tokens_after, 
                        special_tokens[1:]])
    tokens = tokens.reshape(1, len(mask))
    with torch.no_grad():
        model_output = model(input_ids=tokens)
        
    return torch.mean(model_output[0][0][mask, :], 0)
