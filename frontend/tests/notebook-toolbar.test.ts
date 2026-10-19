import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const css=readFileSync(new URL('../src/styles.css',import.meta.url),'utf8');

test('every pressed toolbar button, including fit width, has the visible selection marker',()=>{
  const rules=[...css.matchAll(/\.ink-toolbar button\[aria-pressed=true\]\s*\{([^}]*)\}/g)];
  assert.ok(rules.some(([,body])=>/box-shadow\s*:\s*inset\s+0\s+-3px\s+0\s+currentColor/.test(body)),
    'the shared pressed-button selector must provide the marker, not only drawing-tool buttons');
});

test('generic button hover excludes disabled controls without adding selector specificity',()=>{
  assert.ok(!/(?:^|[},])\s*button:hover\s*\{/m.test(css),'unconditional button:hover must not style disabled controls');
  assert.ok(/button:where\(:not\(:disabled\)\):hover\s*\{/.test(css),'the disabled guard must preserve generic hover specificity');
});

test('button state colors and selection markers update without a native paint transition',()=>{
  const rules=[...css.replace(/\/\*[\s\S]*?\*\//g,'').matchAll(/(?:^|[}])\s*button\s*\{([^}]*)\}/g)];
  assert.ok(rules.length);
  assert.ok(rules.every(([,body])=>!/transition\s*:[^;}]*(?:background|border-color|box-shadow|\ball\b)/.test(body)),
    'theme colors and pressed markers must update immediately instead of leaving stale native button paint');
});

function luminance(hex:string){
  assert.match(hex,/^#[0-9a-f]{6}$/i);
  return hex.slice(1).match(/../g)!.reduce((sum,part,index)=>{
    const value=parseInt(part,16)/255;
    return sum+[.2126,.7152,.0722][index]*(value<=.04045?value/12.92:((value+.055)/1.055)**2.4);
  },0);
}
function contrast(first:string,second:string){
  const values=[luminance(first),luminance(second)].sort((a,b)=>a-b);
  return (values[1]+.05)/(values[0]+.05);
}

for(const [theme,pattern] of [['light',/:root\s*\{([^}]+)\}/],['dark',/:root\[data-theme=dark\]\s*\{([^}]+)\}/]] as const){
  test(`${theme} toolbar enabled text, selection marker and focus retain sufficient token contrast`,()=>{
    const block=css.match(pattern)?.[1];
    assert.ok(block,`${theme} theme tokens must exist`);
    const tokens=Object.fromEntries([...block.matchAll(/--([\w-]+)\s*:\s*(#[0-9a-f]{6})\b/gi)].map(([,key,value])=>[key,value]));
    // Disabled controls are exempt; these thresholds apply to enabled controls.
    for(const [foreground,background,minimum] of [['ink','surface',4.5],['muted','surface',4.5],['primary','primary-soft',3],['focus','surface',3],['focus','primary-soft',3]] as const){
      const ratio=contrast(tokens[foreground],tokens[background]);
      assert.ok(ratio>=minimum,`${theme} ${foreground}/${background}: ${ratio.toFixed(2)}:1 must be at least ${minimum}:1`);
    }
  });
}

test('tool settings reveal their full bounds and can scroll in short windows',()=>{
  const notebook=readFileSync(new URL('../src/PageNotebook.tsx',import.meta.url),'utf8');
  const settings=css.match(/\.ink-tool-settings\s*\{([^}]+)\}/)?.[1];
  assert.ok(settings);
  assert.match(settings,/max-width:calc\(100vw - 48px\)/);
  assert.match(settings,/max-height:calc\(100dvh - 32px\)/);
  assert.match(settings,/overflow:auto/);
  assert.ok(notebook.includes("settings.current?.scrollIntoView({block:'nearest'})"));
});
