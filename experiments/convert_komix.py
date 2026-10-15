"""One-off conversion using whisper.cpp v1.9.5's mapping; not shipped by the app."""
import ast
import hashlib
import json
import struct
from pathlib import Path
import numpy as np

root=Path(__file__).resolve().parents[1]
runtime=root/".local-state/runtime"
original=runtime/"models/komixv2-original"
checkpoint=original/"model.safetensors"
expected="8ce118afc03743d449ec266c3f0ada1027ac9e51c10fe34e13846b902d47c5d0"
with checkpoint.open("rb") as handle:
    assert hashlib.file_digest(handle,"sha256").hexdigest()==expected
    handle.seek(0);header_size=struct.unpack("<Q",handle.read(8))[0]
    assert 0<header_size<16*1024**2
    tensors=json.loads(handle.read(header_size))
tensors.pop("__metadata__",None)
assert len(tensors)==947
assert "proj_out.weight" not in tensors and "model.decoder.embed_tokens.weight" in tensors
config=json.loads((original/"config.json").read_text())
assert config["model_type"]=="whisper" and config["num_mel_bins"]==80 and config.get("tie_word_embeddings",True)
source=runtime/"sources/whisper.cpp/models/convert-h5-to-ggml.py"
tree=ast.parse(source.read_text())
mapping=next(ast.literal_eval(node.value) for node in tree.body if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="conv_map" for t in node.targets))
with (runtime/"models/ggml-base.bin").open("rb") as handle:
    handle.seek(48);mel_header=handle.read(8);rows,cols=struct.unpack("<2i",mel_header)
    assert (rows,cols)==(80,201)
    mel=handle.read(rows*cols*4)
tokens=json.loads((original/"vocab.json").read_text())
assert len(tokens)==50258 and set(tokens.values())==set(range(len(tokens)))
byte_values=list(range(33,127))+list(range(161,173))+list(range(174,256))
unicode_values=byte_values.copy();extra=0
for byte in range(256):
    if byte not in byte_values:
        byte_values.append(byte);unicode_values.append(256+extra);extra+=1
byte_decoder={chr(c):b for b,c in zip(byte_values,unicode_values)}
target=runtime/"models/ggml-medium-komixv2.bin";staging=target.with_suffix(".download")
header=[0x67676d6c,config["vocab_size"],config["max_source_positions"],config["d_model"],config["encoder_attention_heads"],config["encoder_layers"],
        config.get("max_length") or config["max_target_positions"],config["d_model"],config["decoder_attention_heads"],config["decoder_layers"],80,1]
names=set();parameters=0
with staging.open("wb") as output:
    output.write(struct.pack("<12i",*header));output.write(mel_header+mel);output.write(struct.pack("<i",len(tokens)))
    for text,_ in sorted(tokens.items(),key=lambda item:item[1]):
        encoded=bytes(byte_decoder[c] for c in text)
        output.write(struct.pack("<i",len(encoded)));output.write(encoded)
    for key,tensor in tensors.items():
        assert tensor["dtype"]=="F32"
        shape=tensor["shape"];start,end=tensor["data_offsets"]
        assert 1<=len(shape)<=3 and all(type(d) is int and d>0 for d in shape)
        count=int(np.prod(shape));parameters+=count
        assert end-start==count*4 and 8+header_size+end<=checkpoint.stat().st_size
        name=key.split(".")[1:]
        if name[1]=="layers":
            name[1]="blocks"
            middle=".".join(name[3:-1])
            mapped=("attn.key" if name[0]=="encoder" else "cross_attn.key") if middle=="encoder_attn.k_proj" else mapping[middle]
            name=".".join(name[:3]+[mapped]+name[-1:])
        else:
            name=".".join(name);name=mapping.get(name,name)
        assert name not in names;names.add(name)
        tensor_array=np.memmap(checkpoint,dtype="<f4",mode="r",offset=8+header_size+start,shape=tuple(shape))
        data=np.asarray(tensor_array).squeeze().astype("<f2")
        if name in ("encoder.conv1.bias","encoder.conv2.bias"): data=data.reshape(data.shape[0],1)
        as_f32=data.ndim<2 or name in ("encoder.conv1.bias","encoder.conv2.bias","encoder.positional_embedding","decoder.positional_embedding")
        if as_f32: data=data.astype("<f4")
        assert np.isfinite(data).all()
        encoded=name.encode()
        output.write(struct.pack("<3i",data.ndim,len(encoded),0 if as_f32 else 1))
        output.write(struct.pack("<"+"i"*data.ndim,*reversed(data.shape)));output.write(encoded);data.tofile(output)
        del data,tensor_array
assert parameters==763857920
with staging.open("rb") as handle: digest=hashlib.file_digest(handle,"sha256").hexdigest()
staging.replace(target)
meta={"source_checkpoint_sha256":expected,"source_repository":"seastar105/whisper-medium-komixv2","source_revision":"752b1b5bfa0c8219bca737ea180a4ad7eed1e621",
      "mapping_source_sha256":hashlib.sha256(source.read_bytes()).hexdigest(),"converter":"pinned official HF-to-GGML mapping, streaming F32 safetensors read, same F16 rounding/FP32 exceptions, base mel80 filters",
      "format":"GGML f16","bytes":target.stat().st_size,"sha256":digest,"parameters":parameters,"tensors":len(names),"license":"author checkpoint license not stated; local evaluation only, redistribution not approved"}
(runtime/"models/komixv2-ggml-provenance.json").write_text(json.dumps(meta,indent=2))
print(json.dumps(meta,indent=2))
