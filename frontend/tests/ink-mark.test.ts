import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';

test('text marks preserve literal repeated Unicode and newlines, wrap in the box and scale with the page',async()=>{
  const server=await createServer({configFile:false,server:{middlewareMode:true,hmr:false,ws:false},appType:'custom'});
  try{
    const {default:InkMark}=await server.ssrLoadModule('/src/InkMark.tsx');
    const stroke={id:'text',tool:'text',text:'같은 문장 같은 문장\n\n🙂 <script> & 한글',color:'#123456',width:.025,opacity:.8,input:'mouse',points:[{x:.1,y:.2,pressure:.5},{x:.5,y:.4,pressure:.5}]};
    const draw=(width:number,height:number)=>renderToStaticMarkup(React.createElement('svg',{},React.createElement(InkMark,{stroke,width,height})));
    const html=draw(600,800);
    assert.match(html,/<foreignObject x="60" y="160" width="240" height="160" opacity="0.8"/);
    assert.match(html,/font-size:15px/);
    assert.match(html,/white-space:pre-wrap;overflow-wrap:anywhere/);
    assert.match(html,/같은 문장 같은 문장\n\n🙂 &lt;script&gt; &amp; 한글/);
    assert.doesNotMatch(html,/<script>|<path/);
    assert.match(draw(1200,1600),/<foreignObject x="120" y="320" width="480" height="320"/);
    assert.match(draw(1200,1600),/font-size:30px/);
    const {SourceImage}=await server.ssrLoadModule('/src/SourceLink.tsx');
    const source={image_url:'/page.png',ref:{kind:'ink_note',page:1,source_width:600,source_height:800},ink_snapshot:[stroke]};
    const preview=renderToStaticMarkup(React.createElement(SourceImage,{source}));
    assert.match(preview,/<foreignObject/);assert.match(preview,/같은 문장 같은 문장\n\n🙂/);
  }finally{await server.close();}
});
