# 可执行时间线工具

`scripts/dialogue_timeline.py`只进行本地媒体处理，依赖Python 3.10+、FFmpeg/FFprobe；渲染另需numpy、opencv-python、Pillow，由安装者按环境提供，不自动安装。它按人工确认的区间编译并渲染，不自动找气口、生成声音或识别人物。支持CFR素材；VFR、旋转素材先明确规范化，别静默套错帧号。

所有素材路径相对项目plan文件，绝不放入Skill目录。不同视频可使用分别对齐的音频文件；`audio`省略表示使用同一视频的音轨。每个源的video/audio必须已经以同一个零点对齐。`speed`始终相对该输入，不能把未知既有速度当成1倍原声。

```json
{
  "fps": 24,
  "canvas": [720, 1280],
  "sources": [
    {"id":"clip-a", "video":"media/clip-a.mp4", "existing_speed_note":"original generation"}
  ],
  "segments": [
    {"id":"question", "source":"clip-a", "start_frame":0, "end_frame":72, "speed":1.05, "speaker":"A"},
    {"id":"answer", "source":"clip-a", "start_frame":80, "end_frame":200, "speed":1.05, "speaker":"B"}
  ],
  "captions": [
    {"source":"clip-a", "start_frame":0, "end_frame":65, "text":"本次已确认的问题"},
    {"source":"clip-a", "start_frame":80, "end_frame":190, "text":"来自本人原稿的回答"}
  ],
  "overlays": []
}
```

范围统一为左闭右开源帧；例如0—72保留72帧。源内多余空白由`segments`间缺口表达；希望保留换人空隙时延长相关源区间，只选经过检查的真实静默画面。不要用脚本默认加静音或定格，它不会替你决定该留多久。

源可提供`crop:[x,y,width,height]`，不提供则全帧；裁切后的比例必须与输出画布相符，拒绝拉伸。字幕先编译成SRT；SRT不会自动烧入画面。要沿用现有文字层，可填`overlays`，每项为`source/start_frame/end_frame/image`，图片必须是输出画布尺寸的透明PNG，列表顺序为叠加顺序。标题/字幕用同一源时间映射；已烤字幕素材不要再重复叠字。也可把编译后的字幕交现有排版工具，完成后重新验证最终文件。

```text
python -B scripts/dialogue_timeline.py compile --plan /project/plan.json --out /project/edit-v1.json --ffprobe ffprobe
python -B scripts/dialogue_timeline.py render --edl /project/edit-v1.json --out /project/preview-v1.mp4 --work-dir /project/work --ffmpeg ffmpeg --ffprobe ffprobe
python -B scripts/dialogue_timeline.py verify --edl /project/edit-v1.json --out /project/preview-v1.mp4 --ffmpeg ffmpeg --ffprobe ffprobe
```

路径是调用示意，由安装者替换。先创建输出父目录和work目录。输出必须使用新文件名；不自动覆盖或删除旧成片。临时PCM和编码日志只在work中的独立临时子目录生成，退出时清理该工具自己创建的子目录。失败可能保留不完整MP4，不能把它当成功文件，下一次用新文件名。

编译输出记录输入摘要、每段源帧序列、请求/实际速度、输出帧区间和字幕。渲染前复核摘要；音频和画面使用同一取整时长。视频按源帧顺序解码采样，音频atempo保持音调，最终一次H.264/AAC编码。独立音频补丁应事先准备好，不通过字幕掩盖错误。

回改时修改plan的选定源区间，不将已变速MP4当新原片。未改片段的`source_frames`、音频源范围与`applied_speed`应一致；后续输出时间可顺延。编译不做主观验收，verify只证明帧数、画幅、音视频时长和完整解码，仍须做实际导出内容、留白、字幕及听感检查。
