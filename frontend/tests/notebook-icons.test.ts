import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {readFileSync} from 'node:fs';
import {createServer} from 'vite';

test('A handwriting SVG assets match app glyphs at20 and24 with theme color inheritance',async()=>{
  const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
  try{
    const {default:Icon}=await server.ssrLoadModule('/src/Icon.tsx');
    for(const name of ['pen','highlighter','stroke-eraser','lasso','hand','undo','redo'])for(const size of [20,24]){
      const markup=renderToStaticMarkup(React.createElement(Icon,{name,size}));
      assert.match(markup,new RegExp(`width="${size}" height="${size}"`));
      assert.match(markup,/stroke="currentColor" stroke-width="1.65"/);
      assert.match(markup,/aria-hidden="true" focusable="false"/);
      const asset=readFileSync(new URL('../public/icons/notebook/'+(name==='stroke-eraser'?'eraser':name)+'.svg',import.meta.url),'utf8');
      for(const [,path] of markup.matchAll(/\sd="([^"]+)"/g))assert.ok(asset.includes(`d="${path}"`));
    }
  }finally{await server.close();}
});
