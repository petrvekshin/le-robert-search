# A search tool for [Le Robert French Dictionary](https://dictionnaire.lerobert.com/) to help you determine word sense in your text

## How to use it

To determine the word sense, enter your French text in the textbox on the left side of the page. Select the model for computing contextual embeddings and choose the word you want to find the sense for. Relevant definitions with example sentences will appear on the right side. Words in example sentences are highlighted based on their cosine similarity scores. The GIF image below demonstrates how the scores change depending on the sense of the word "langue".

![](./images/le-robert-search.gif)

## How it works

Brief instructions are provided in `Le Robert.ipynb`. After scraping the content of the dictionary and processing it, the tool works locally. Word embeddings are computed using multilingual models for sentence similarity. Instead of performing mean pooling on the entire sentence, pooling is performed on the word for which the example sentence is given.

## How it can be improved

Some models with fewer dimensions, such as `sentence-transformers/paraphrase-multilingual-mpnet-base-v2` (768 dimensions), outperform models with more dimensions, such as `intfloat/multilingual-e5-large` (1024 dimensions), in terms of the raw cosine similarity score. Feel free to experiment with different models and scores.

Example sentences are not provided for certain senses, requiring the user to analyze these senses separately. An area for potential improvement is to generate example sentences based on definitions using GPT models.

