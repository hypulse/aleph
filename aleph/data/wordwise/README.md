# Word Wise glossaries

Short hints that aleph writes above harder English words in e-books.

| File | Hints | Source | License |
| --- | --- | --- | --- |
| `en-ko.tsv` | Korean | English entries of the Korean Wiktionary, extracted by [Wiktextract](https://github.com/tatuylonen/wiktextract) ([kaikki.org](https://kaikki.org/kowiktionary/)) | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) |
| `en-en.tsv` | English | [Princeton WordNet 3.0](https://wordnet.princeton.edu) | WordNet 3.0 license, see `LICENSE.WordNet` |

The third column, how common each word is (Zipf scale x 10), comes from
[wordfreq](https://github.com/rspeer/wordfreq) by Robyn Speer, whose data is
CC BY-SA 4.0. The files are rebuilt with `aleph/tools/wordwise/build.py`.
