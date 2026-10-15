"""Conservative local checks; the live creator page remains authoritative."""
import re

LIMITS = {'title': 20, 'caption': 1000, 'tags': 10, 'title_count_mode': 'utf16_conservative'}
DEFAULTS = dict(visibility='公开', allow_download=False, collection='', location=False,
                activity=False, ai_declaration='unknown')
BLOCKING_JOB_STATES = {'running', 'stopping', 'awaiting_manual', 'attention', 'verified_absent'}


def units(value):
    if not isinstance(value, str):
        raise ValueError('标题、正文与话题必须是文字')
    try:
        return len(value.encode('utf-16-le')) // 2
    except UnicodeEncodeError as exc:
        raise ValueError('文字包含无效字符，请重新输入') from exc


def normalize_tags(tags):
    if not isinstance(tags, list):
        raise ValueError('话题必须是列表')
    cleaned = []
    for tag in tags:
        if not isinstance(tag, str):
            raise ValueError('话题必须是文字')
        tag = tag.strip().lstrip('#').strip()
        if not tag or re.search(r'[\s#\x00-\x1f]', tag):
            raise ValueError('单个话题不能为空，也不能包含空格、换行或井号')
        if tag.casefold() not in {value.casefold() for value in cleaned}:
            cleaned.append(tag)
    if len(cleaned) > LIMITS['tags']:
        raise ValueError('小红书话题最多10个')
    return cleaned


def compose_caption(caption, tags):
    units(caption)
    caption = caption.strip()
    topics = ' '.join('#' + tag for tag in normalize_tags(tags))
    return caption + ('\n\n' if caption and topics else '') + topics


def settings(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError('包含不支持的小红书发布选项')
    result = {**DEFAULTS, **value}
    if result['visibility'] not in ['公开', '仅自己可见']:
        raise ValueError('可见范围须为公开或仅自己可见')
    if result['ai_declaration'] not in ['unknown', 'none', 'contains_ai']:
        raise ValueError('请选择有效的AI内容声明')
    if not isinstance(result['collection'], str):
        raise ValueError('合集名称必须是文字')
    for key in ['allow_download', 'location', 'activity']:
        if type(result[key]) is not bool:
            raise ValueError('发布开关必须为布尔值')
    return result


def validate(asset, for_execution=False):
    title, caption = asset.get('title', ''), asset.get('caption', '')
    tags = normalize_tags(asset.get('tags', []))
    opts = settings(asset.get('settings', {}))
    if units(title) > LIMITS['title']:
        raise ValueError('小红书标题超过20个保守计数单位，请手动修改；不会自动截断')
    if units(caption) > LIMITS['caption'] or units(compose_caption(caption, tags)) > LIMITS['caption']:
        raise ValueError('正文与追加话题合计超过1000个保守计数单位，请手动修改')
    if for_execution:
        if not title.strip():
            raise ValueError('请先确认小红书标题，不能以审查稿或文件名自动替代')
        if opts['ai_declaration'] == 'unknown':
            raise ValueError('请先确认是否包含AI生成内容，再准备发布')
    return {'title': title, 'caption': caption, 'tags': tags, 'settings': opts}


def annotations(asset):
    errors = []
    try:
        validate(asset)
    except ValueError as exc:
        errors.append(str(exc))
    try:
        total = units(compose_caption(asset.get('caption', ''), asset.get('tags', [])))
    except ValueError:
        total = None
    try:
        counts = dict(title=units(asset.get('title', '')), caption=units(asset.get('caption', '')),
                      total=total, tags=len(asset.get('tags', [])))
    except (ValueError, TypeError):
        counts = {}
    return dict(validation_errors=errors, counts=counts)
