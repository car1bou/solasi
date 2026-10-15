# Additional public Korean audio sources

Checked 2026-10-14 KST. No app files were edited. No ASR inference was performed. Original small audio files were read in memory only to verify integrity and duration; no audio files were saved.

## Pansori TEDxKR: 24 actual lecture fragments

Official source: https://github.com/yc9701/pansori-tedxkr-corpus
License: https://github.com/yc9701/pansori-tedxkr-corpus/blob/master/LICENSE (CC BY-NC-ND 4.0). Use unchanged originals for noncommercial evaluation, not modified audio distribution or product bundling.

The publisher describes Korean TEDx talks from 2010-2014, about three hours from 41 speakers, segmented at subtitle boundaries with manual alignment. Actual checked repository tree has 2,989 FLAC files (174,226,603 bytes). Pinned revision: b24c3933cb44192e8f1e0ca76ccfe01526e5d09c.

Anonymous file-list API GET 200: https://api.github.com/repos/yc9701/pansori-tedxkr-corpus/git/trees/master?recursive=1
Original per-file URL: https://raw.githubusercontent.com/yc9701/pansori-tedxkr-corpus/<revision>/<path>
Transcript rows: clip_id followed by text in *.trans.txt. Exact ID and transcript Git blob SHA were checked. Per-talk README provides Speaker, Gender, Year, Place and Title. Gender labels contain a typo/unknown value and were not independently verified. A joint presentation was replaced by a single-speaker talk before inference.

Manifest: /private/tmp/pansori-subset-24.json
SHA256: 390cceaeb2c51f9c083b12e04abeaaec2b86854f16bbce6231773f438fbe1ef6
24 original clips from 12 single-speaker sources, two per source. Reference >=15 Unicode letters/numbers; evenly spaced speaker IDs and one-third/two-thirds clip positions, fixed before inference. Actual 1,935,402 bytes, 107.796 seconds, min 1.899/max 10.5 seconds; all 16kHz mono. Individual audio SHA256/Git blob SHA/FLAC STREAMINFO checks are in the manifest. These are short lecture fragments, not complete lectures or real meetings.

## Deeply Korean Read Speech Corpus: 18 real room recordings

Official source: https://github.com/deeplyinc/Korean-Read-Speech-Corpus
Official distributor: https://www.openslr.org/97
Both list CC BY-NC-ND 4.0. Pinned revision: 1c9cdb8ca1ba79bf982c97b16fb40657420c9cba. The actual official GitHub tree contains 1,697 separately downloadable WAV files, so the 0.5GB tar archive is unnecessary.

Metadata path: dataset/Korean_Read_Speech_Corpus_sample.json (784,839 bytes), Git blob SHA 0868369a25914f7378f3ac4088b7708d9a70f3d2. Fields include text, text_code, subjectID, speaker, age, sex, noise, location, distance, device, text_sentiment, voice_sentiment, rms, length. Exact metadata Git blob SHA was checked.

Important correction: the public sample metadata has only distance=0 (0.4m) and device=0 (iPhone X). Three distances and two devices in README refer to the full commercial corpus, not supported public sample conditions. Three actual rooms: AirbnbStudio, AnechoicChamber, DanceStudio. Two reported female speakers (20 and 49); dialogue scripts are read, not spontaneous meetings.

Manifest: /private/tmp/deeply-subset-18.json
SHA256: 32f79b5b00592c291666633bddcc6543d74a400fff1058d04dc6e73256cdf559
Selection before inference: exact shared text/text_code/speaker/vocal sentiment/device/distance/noise across all three rooms; two speakers times three vocal sentiments times three rooms. Six matched recording groups, five unique reference texts, not 18 independent speakers or texts. Report room comparisons as paired observations. Actual 2,721,410 bytes, 85.0193125 seconds; all 16kHz 16bit mono. Original HTTP/Git blob SHA/SHA256 and WAV duration against metadata checked for every file.

## Other checked candidates and current barriers

Zeroth Korean: https://www.openslr.org/40 -- CC BY 4.0; official test 457 utterances/10 speakers/1.2h, full tar 10GB. The project is Kaldi-based; archive metadata files were not inspected here. No 10GB download was made. Google mirror HEAD returned 403; other original audio mirrors were not downloaded.

Common Voice: https://commonvoice.mozilla.org/fr/datasets -- official current list has Scripted Speech 26.0 Korean, CC0-1.0, MP3 208.26MB. Official API https://mozilladatacollective.com/api-reference and https://mozilladatacollective.com/api-reference/docs requires an account API key and dataset terms acceptance for downloads. Anonymous small audio access was not established. Optional speaker demographics can be missing.

AI Hub real meeting dataset: https://www.aihub.or.kr/aihubdata/data/view.do?currMenu=115&topMenu=100&aihubDataSe=data&dataSetSn=464 -- 7,000h WAV/JSON including meetings, parliament, podcasts and broadcast conversations. Actual HTML confirms sample download button invokes fnLoginLink(); full API requires dataset approval. No anonymous bypass was attempted.

AI Hub university lecture dataset: https://www.aihub.or.kr/aihubdata/data/view.do?currMenu=115&topMenu=100&aihubDataSe=data&dataSetSn=71627 -- real Korean university lecture audio/transcripts, official download requires application. Original files not collected here.

AI Hub FAQ https://www.aihub.or.kr/aihubnews/faq/list.do prohibits redistribution of original/simple edited data to third parties. Arbitrary Hugging Face copies should not be treated as official data distribution.

## Scope

Verified: official provenance/license, two corpora anonymous small original HTTP access, transcript pairing, frozen revisions/hashes, actual audio formats/durations and public sample conditions.
Not checked: ASR accuracy/ranking, long real meetings, overlapping speakers, 2m/4m microphone distance, independent speaker demographic verification, full corpus acquisition or paid/API signup.
