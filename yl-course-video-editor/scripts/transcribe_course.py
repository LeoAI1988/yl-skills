"""External faster-whisper transcription; runtime audio/model/hotwords stay outside core. MIT."""
import argparse
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('audio'); p.add_argument('output'); p.add_argument('--hotwords')
    p.add_argument('--model', default='medium'); p.add_argument('--threads', type=int, default=8)
    a = p.parse_args()
    out = Path(a.output)
    if out.exists():
        raise ValueError('Existing transcript refused; use a new version')
    prompt = ''
    if a.hotwords:
        table = json.loads(Path(a.hotwords).read_text(encoding='utf-8-sig'))
        prompt = '、'.join(w for values in table.get('words', {}).values() for w in values)[:400]
    from faster_whisper import WhisperModel
    model = WhisperModel(a.model, device='cpu', compute_type='int8', cpu_threads=a.threads)
    segments, info = model.transcribe(a.audio, language='zh', beam_size=5, word_timestamps=True,
        initial_prompt=prompt, vad_filter=True,
        vad_parameters={'min_silence_duration_ms': 300, 'speech_pad_ms': 60})
    result = {'audio': a.audio, 'duration': info.duration, 'language': info.language, 'segments': []}
    for s in segments:
        result['segments'].append({'start': s.start, 'end': s.end, 'text': s.text.strip(),
            'words': [{'start': w.start, 'end': w.end, 'word': w.word, 'prob': w.probability}
                      for w in (s.words or [])]})
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'segments': len(result['segments']), 'duration': info.duration}))


if __name__ == '__main__':
    main()
