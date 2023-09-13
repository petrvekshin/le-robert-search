import warnings
warnings.filterwarnings('ignore')

import os
import json

import matplotlib.pyplot as plt
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from starlette.responses import FileResponse
from pydantic import BaseModel

import treetaggerwrapper as ttpw
from transformers import AutoTokenizer, AutoModel
import torch

import lerobert.processing as lrp


html_files = set(lrp.list_html_files(html_path='./assets/html/processed'))

with open('./assets/word_map.json', 'r', encoding='utf-8') as f:
    word_map = json.load(f)

tagger = ttpw.TreeTagger(TAGLANG='fr')

model_names = ["sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
               "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"]
tokenizers = []
models = []
for model_name in model_names:
    tokenizers.append(AutoTokenizer.from_pretrained(model_name))
    models.append(AutoModel.from_pretrained(model_name))


def css_color_string(value):
    colormap = 'cool'
    color = plt.get_cmap(colormap)(value*0.9 if (value > 0.0) else 0.0)
    color_str = f'rgba({color[0]*255:.3f}, {color[1]*255:.3f}, {color[2]*255:.3f}, {0.50})'
    return color_str


with open('./assets/css/textbox.css', 'w', encoding='utf-8') as f:
    f.write(f'@charset "UTF-8";\n\n#textbox::selection {{color:#000000; background-color:{css_color_string(1.0)};}}\n')

cos = torch.nn.CosineSimilarity(dim=0, eps=1e-8)


class DefinitionsRequest(BaseModel):
    text: str
    selection_start: int
    selection_end: int
    model_index: int


def generate_definitions_response(payload, tagger, tokenizer, model):
    # without the text before and after the selected one, lemmas can be wrong
    tags = lrp.tag_text(payload.text[payload.selection_start:payload.selection_end], tagger)
    words = set()
    for tag in tags:
        words.add(tag['word'].lower())
        words.update(set(tag['lemma'].lower().split('|')))
    
    selected_text_embeddings = lrp.compute_embeddings_selected_text(payload, tokenizer, model, max_length=510)

    loaded_def_tags = []
    loaded_def_inds = set()
    for word in words:
        if word not in word_map:
            continue
        for word_path in word_map[word]:
            def_tags = lrp.find_definitions(lrp.read_html_file(word_path, html_path='./assets/html/processed/'))
            def_embedding_path = f'./assets/embeddings/{model_names[payload.model_index]}/{word_path}.pt'
            def_embeddings = torch.load(def_embedding_path) if os.path.isfile(def_embedding_path) else None
            for def_ind, example_ind_start, num_examples in word_map[word][word_path]:
                if (word_path, def_ind, example_ind_start, num_examples) in loaded_def_inds:
                    continue
                def_tag = def_tags[def_ind]
                example_tags = def_tag.find_all(True, class_='d_xpl')
                for example_ind in range(num_examples):
                    example_tag = example_tags[example_ind]
                    cos_sim = cos(selected_text_embeddings, def_embeddings[example_ind_start+example_ind]).item()
                    colors = css_color_string(cos_sim)
                    for word_tag in example_tag.find_all(True, class_='word'):
                        word_tag['title'] = f'{cos_sim:.3f}'
                        word_tag['style'] = f'background-color: {colors};'
                loaded_def_tags.append(str(def_tag))
                loaded_def_inds.add((word_path, def_ind, example_ind_start, num_examples))
    if loaded_def_tags:
        html_response = HTMLResponse(content='\n'.join(loaded_def_tags), status_code=200)
    else:
        content = '<div class="b"><h3><span class="notBold">Aucun résultat trouvé</span></h3></div>'
        html_response = HTMLResponse(content=content, status_code=200)

    return html_response


app = FastAPI()


@app.get('/')
async def read_root():
    return FileResponse('./assets/index.html')


@app.get('/{dirname}/{filename}')
async def read_file(dirname, filename):
    if dirname == 'html':
        if filename[:-5] not in html_files:
            raise HTTPException(status_code=404, detail=f'{filename[:-5]}.html not found')
        return FileResponse(f'./assets/html/processed/{filename}')       
    if dirname == 'image-thumbnails':
        return FileResponse(f'./assets/images/thumbnails/{filename}')
    # css, js, audio files
    return FileResponse(f'./assets/{dirname}/{filename}')
      

@app.get('/models')
async def read_models():
    tags = []
    for ind, model_name in enumerate(model_names):
        tags.append(f'<option value="{ind}">{model_name}</option>')
    return HTMLResponse(content=''.join(tags), status_code=200)


@app.get('/colorbar')
async def read_colorbar():
    tags = []
    for val in [-10, *range(0, 11)]:
        tag = f'<span class="colorbar-element"; style="background-color: {css_color_string(val/10)};">{val/10:.1f}</span>'
        tags.append(tag)    
    return HTMLResponse(content=''.join(tags), status_code=200)


@app.post('/definitions')
async def find_definitions(payload: DefinitionsRequest):
    return generate_definitions_response(payload,
                                         tagger,
                                         tokenizers[payload.model_index],
                                         models[payload.model_index])
