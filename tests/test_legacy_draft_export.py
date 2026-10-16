import unittest
from pathlib import Path
import subprocess
from scripts.export_legacy_drafts import checked_origin


class LegacyDraftExportTests(unittest.TestCase):
    def test_raw_undefined_roundtrip_and_unsupported_values(self):
        source = (Path(__file__).resolve().parents[1] / "macos/LegacyDraftExport.swift").read_text()
        codec = source.split("// BEGIN RAW_DRAFT_CODEC\n", 1)[1].split("// END RAW_DRAFT_CODEC", 1)[0]
        checks = r"""
        const original={key:'fixture',backup:undefined,nested:{optional:undefined},values:[undefined,null,{optional:undefined}],dirty:false};
        const expected=[['backup'],['nested','optional'],['values',0],['values',2,'optional']];
        const paths=rawDraftUndefinedPaths(original);
        assert.deepEqual(paths,expected);
        const restored=JSON.parse(JSON.stringify(original));
        for(const path of paths){let parent=restored;for(const part of path.slice(0,-1))parent=parent[part];const last=path.at(-1);Object.defineProperty(parent,last,{value:undefined,enumerable:true,writable:true,configurable:true});}
        assert.deepEqual(restored,original);
        assert.ok(Object.hasOwn(restored,'backup'));
        assert.ok(Object.hasOwn(restored.values,0));
        assert.equal(restored.values[1],null);
        assert.equal(JSON.stringify({backup:undefined}),JSON.stringify({}));
        assert.notEqual(JSON.stringify(rawDraftUndefinedPaths({backup:undefined})),JSON.stringify(rawDraftUndefinedPaths({})));
        assert.equal(JSON.stringify([undefined]),JSON.stringify([null]));
        assert.notEqual(JSON.stringify(rawDraftUndefinedPaths([undefined])),JSON.stringify(rawDraftUndefinedPaths([null])));
        for(const bad of [new Map(),new Date(),[,,],NaN,1n])assert.throws(()=>rawDraftUndefinedPaths({bad}));
        const cycle={};cycle.self=cycle;assert.throws(()=>rawDraftUndefinedPaths(cycle));
        console.log('undefined object/array roundtrip and distinct absent/null paths passed');
        """
        result = subprocess.run(["node", "--input-type=module", "-e", "import assert from 'node:assert/strict';\n" + codec + checks], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_exact_legacy_origin(self):
        self.assertEqual(checked_origin("http://127.0.0.1:62434/"), "http://127.0.0.1:62434")

    def test_rejects_other_origins_and_embedded_paths(self):
        for value in ["https://127.0.0.1:62434", "http://localhost:62434", "http://127.0.0.1", "http://127.0.0.1:62434/api", "http://user@127.0.0.1:62434", "http://127.0.0.1:62434?x=1", "http://127.0.0.1:62434/#x", "http://127.0.0.1:62434?", "http://127.0.0.1:62434#", "http://127.0.0.1:0", "http://127.0.0.1:99999"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                checked_origin(value)


if __name__ == "__main__":
    unittest.main()
