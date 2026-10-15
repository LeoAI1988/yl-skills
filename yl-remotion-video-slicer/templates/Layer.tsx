import React, {useEffect, useState} from 'react';
import {cancelRender, continueRender, delayRender, staticFile} from 'remotion';

// Each generated timeline/layer has its own JSX node; this is its shared renderer.
export const Layer = ({title, mask, styleConfig = {}, font}: any) => {
  const [handle] = useState(() => delayRender('Loading local font'));
  useEffect(() => {
    const load = async () => {
      if (font) {
        const face = new FontFace('SliceFont', `url(${staticFile(font)})`,
          {weight: String(styleConfig.font_weight ?? 900)});
        await face.load(); document.fonts.add(face);
      }
      await document.fonts.ready;
      continueRender(handle);
    };
    load().catch(cancelRender);
  }, [handle, font]);
  const common: React.CSSProperties = {
    position: 'absolute', fontFamily: font ? 'SliceFont' : (styleConfig.font_family ?? 'sans-serif'),
    fontWeight: styleConfig.font_weight ?? 900, color: styleConfig.color ?? '#ffffff',
    lineHeight: styleConfig.line_height ?? 1.2, textShadow: styleConfig.shadow ?? '3px 3px 0 #000',
    whiteSpace: 'pre-wrap', boxSizing: 'border-box',
  };
  if (mask) return <div style={{...common, left: mask.rect[0], top: mask.rect[1], width: mask.rect[2],
    height: mask.rect[3], background: mask.color ?? '#111111', color: mask.text_color ?? '#ffffff',
    fontSize: mask.font_size ?? 40, textAlign: 'center', display: 'flex', alignItems: 'center',
    justifyContent: 'center', padding: 12, overflow: 'hidden', textShadow: 'none'}}>{mask.text ?? ''}</div>;
  if (title) return <>
    {styleConfig.title_panel && <div style={{position: 'absolute',
      left: styleConfig.title_panel.rect[0], top: styleConfig.title_panel.rect[1],
      width: styleConfig.title_panel.rect[2], height: styleConfig.title_panel.rect[3],
      backgroundColor: styleConfig.title_panel.color ?? '#000000',
      opacity: styleConfig.title_panel.opacity ?? 0.6,
      borderRadius: styleConfig.title_panel.radius ?? 0}} />}
    <div style={{...common, left: styleConfig.title_left ?? 80,
      top: styleConfig.title_top ?? 50, width: styleConfig.title_width ?? '90%',
      fontSize: styleConfig.font_size ?? 64, textAlign: styleConfig.title_align ?? 'left'}}>
      {title.lines.map((line: string, i: number) => <div key={i}
        style={{color: styleConfig.line_colors?.[i] ?? common.color}}>{line}</div>)}
    </div>
  </>;
  return null;
};
