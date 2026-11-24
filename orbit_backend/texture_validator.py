"""Independent reader for the self-contained, single-mesh Orbit T2 profile."""
import io
import json
import struct
from pathlib import Path

import numpy as np
from PIL import Image


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_mesh(path):
    data = Path(path).read_bytes()
    require(len(data) >= 28 and struct.unpack_from('<4sII', data) == (b'glTF', 2, len(data)), 'Invalid GLB header')
    offset = 12
    chunks = []
    for kind in (b'JSON', b'BIN\0'):
        size, tag = struct.unpack_from('<I4s', data, offset)
        offset += 8
        require(tag == kind and size % 4 == 0 and offset + size <= len(data), 'Invalid chunk')
        chunks.append(data[offset:offset + size])
        offset += size
    doc, binary = json.loads(chunks[0]), chunks[1]
    require(offset == len(data) and doc['asset']['version'] == '2.0', 'Invalid GLB structure')
    buffers = doc['buffers']
    require(len(buffers) == 1 and 'uri' not in buffers[0] and 0 <= len(binary)-buffers[0]['byteLength'] <= 3, 'Invalid embedded buffer')

    def item(items, index):
        require(type(index) is int and 0 <= index < len(items), 'Invalid reference')
        return items[index]

    def view(index):
        v = item(doc['bufferViews'], index)
        start, length = v.get('byteOffset', 0), v['byteLength']
        require(v['buffer'] == 0 and start >= 0 and length > 0 and start + length <= buffers[0]['byteLength'] and 'byteStride' not in v, 'Invalid or interleaved buffer view')
        return binary[start:start+length]

    def array(index, shape, components):
        a = item(doc['accessors'], index)
        require(a['type'] == shape and a['componentType'] in components and 'sparse' not in a and not a.get('normalized'), 'Unsupported accessor')
        dtype = np.dtype({5126:'<f4',5125:'<u4',5123:'<u2',5121:'u1'}[a['componentType']])
        n = {'SCALAR':1,'VEC2':2,'VEC3':3}[shape]
        buf, start, count = view(a['bufferView']), a.get('byteOffset',0), a['count']
        require(count > 0 and start >= 0 and start % dtype.itemsize == 0 and start+count*n*dtype.itemsize <= len(buf), 'Invalid accessor bounds')
        result = np.frombuffer(buf, dtype=dtype, offset=start, count=count*n).reshape(count,n)
        require(np.isfinite(result).all(), 'Nonfinite accessor')
        return result

    # Permit identity grouping nodes emitted by trimesh; reject transforms or instancing.
    nodes = doc['nodes']
    visited = set()
    def visit(i):
        node = item(nodes,i)
        require(i not in visited and not {'skin','matrix','rotation','translation','scale'} & node.keys(), 'Unsupported scene transform or instance')
        visited.add(i)
        for child in node.get('children',[]): visit(child)
    for root in item(doc['scenes'],doc.get('scene',0))['nodes']: visit(root)
    require([nodes[i]['mesh'] for i in visited if 'mesh' in nodes[i]] == [0] and len(doc['meshes']) == 1, 'Expected one mesh instance')
    primitives = doc['meshes'][0]['primitives']
    require(len(primitives)==1 and primitives[0].get('mode',4)==4, 'Expected indexed triangles')
    prim = primitives[0]
    vertices = array(prim['attributes']['POSITION'],'VEC3',{5126})
    faces = array(prim['indices'],'SCALAR',{5121,5123,5125}).reshape(-1,3)
    require(faces.max() < len(vertices), 'Invalid vertex index')
    return vertices, faces, doc, prim, array, view


def validate(source, textured):
    v,f,*_ = read_mesh(source)
    w,g,d,p,array,view = read_mesh(textured)
    require(np.array_equal(v[f],w[g]), 'Triangle positions, order or winding changed')
    uv = array(p['attributes']['TEXCOORD_0'],'VEC2',{5126})
    require(len(uv)==len(w) and ((uv>=0)&(uv<=1)).all(), 'Invalid UVs')
    require(len(d['materials'])==len(d['textures'])==len(d['images'])==1 and p['material']==0, 'Invalid material chain')
    ref = d['materials'][0]['pbrMetallicRoughness']['baseColorTexture']
    require(ref['index']==0 and ref.get('texCoord',0)==0 and d['textures'][0]['source']==0, 'Invalid texture reference')
    image = d['images'][0]
    require(image['mimeType']=='image/png' and 'uri' not in image, 'Expected embedded PNG')
    with Image.open(io.BytesIO(view(image['bufferView']))) as im:
        require(im.format=='PNG', 'Texture is not PNG')
        pixels = np.array(im.convert('RGB'))
    return w,g,uv,pixels
