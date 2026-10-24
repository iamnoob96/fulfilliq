# Dataset attribution and acquisition

Dataset: **Brazilian E-Commerce Public Dataset by Olist**.
Provider: **Olist**, published by Olist and collaborators on
[Kaggle](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce).
It contains anonymized historical Brazilian marketplace orders from 2016–2018.
The project imports the nine original relational CSVs, not a preprocessed ML table.

Original dataset license: **Creative Commons Attribution-NonCommercial-ShareAlike 4.0**
([CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)). Retain Olist
attribution, the original source and license links, and disclose transformations when
sharing derived datasets. Data reuse is for this noncommercial university project.
The dataset license applies independently of any future software license.

Public download mirror:
[miminmoons/olist-ecommerce-for-delivery-and-review-prediction](https://huggingface.co/datasets/miminmoons/olist-ecommerce-for-delivery-and-review-prediction/tree/main/data).
Pinned data commit:
[`2d912b5439d1c42d8c0e6ae84b906f995cbbbeb4`](https://huggingface.co/datasets/miminmoons/olist-ecommerce-for-delivery-and-review-prediction/commit/2d912b5439d1c42d8c0e6ae84b906f995cbbbeb4).
The commit describes its CSVs as unprocessed data sourced from Kaggle. The mirror's
dataset card labels its repository MIT; FulfillIQ retains the original Olist dataset
license and does not infer permission to relicense Olist data from that card.

No credentials or paid APIs are used by the downloader. A network failure may leave
already completed CSVs and a partial manifest; rerun to reuse valid files and fetch the
remaining files. Temporary partial files are removed on handled failures. A force-download
only replaces an existing file after the new response passes header validation.
Manual acquisition follows the same filenames and validation pipeline.

Transformations performed: exact duplicate removal, typed timestamp/numeric coercion,
reported invalid/missing values, geographic means, dimensional copies, safe child-table
aggregation and descriptive historical metrics. Raw files are never edited.
The source review text is primarily Portuguese and remains unmodified apart from empty
field normalization. Separate Portuguese TF-IDF/sentiment analysis and interpretable
lexical themes are documented in `MINING_AND_NLP.md`; no translation API or verified
logistics complaint classifier is claimed.

Raw data, download manifests, generated databases/reports and model files are excluded
from version control. Do not redistribute original or derived data without retaining
the original license/attribution. Synthetic fixtures in `tests/` are explicitly authored
test cases and are not presented as Olist records or empirical project results.
