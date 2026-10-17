# Runtime distribution audit: 2026-10-17

Read-only source and release snapshot. This covers the 47 adapter entries in the
50-entry Core catalog at `8f52b1844fc4eaa06036a42d8c4848faa67a6212`, not every
repository in the organization. Core, the Office umbrella and Autodesk Product
Help are excluded. Source HEAD and published tag are separate identities.

The [machine-readable inventory](runtime-distribution-inventory-2026-10-17.json)
retains exact source commits, dependency classes, execution evidence and release
asset URLs/sizes. Source classification is not live host acceptance.

## Key findings

- Host Python and external Python must be classified by the actual process.
  GIMP, Krita, Mari and Marmoset have thin host Python scripts plus a separate
  service. Cinema4D and FreeCAD also launch host-owned worker interpreters.
  Maya/3ds Max host Python plus a Rust server is a different architecture.
- 14 of the 47 catalog adapters declare mandatory non-Core third-party
  dependencies. This is an inventory, not 14 proven violations: external bridge
  dependencies are permitted when justified and managed by the shared runtime.
- Absence of an interpreter in an adapter archive does not prove startup works
  on a machine without Python. An adapter wheel and a complete runtime are
  different deliverables.

## Actual artifact measurements

Only these two archives were downloaded and inspected locally, without
extracting or running their code. Other inventory sizes come from GitHub release
metadata. All values below are bytes, not estimated installed footprints.

| Artifact | Compressed | Top-level expanded | Nested payload expanded |
|---|---:|---:|---:|
| [OBS 1.5.2 Windows runtime ZIP](https://github.com/dcc-mcp/dcc-mcp-obs/releases/download/v1.5.2/dcc-mcp-obs-1.5.2-windows-runtime.zip) | 256,854 | 281,708 | 863,151 |
| [Photoshop 0.1.43 Windows archive](https://github.com/dcc-mcp/dcc-mcp-photoshop/releases/download/v0.1.43/dcc-mcp-photoshop-windows.tar.gz) | 36,341,684 | 111,350,847 | 0 |

Nested expansion is reported separately; adding it to the outer expanded size
double-counts the nested archive representation. These are unlike products and
build layouts, so the difference is **not** an achieved optimization.

OBS contains adapter/runtime wheels, manifests and a native plug-in ZIP, but no
CPython interpreter. The included runtime wheel is **0.1.0**, not 0.2.0. Its small
size therefore cannot establish a complete no-Python installation. Photoshop
includes `python310.dll` (4,456,448 bytes), a launcher (5,841,920 bytes) and Core
`_core.pyd` (57,432,064 bytes). Core is the largest observed component; Python
deduplication alone will not explain the whole size opportunity.

Locally computed SHA-256 values match the release metadata:

- OBS: `d8c7bb66d192eaac3490b8a991a4fa2d6da4ad1dac8a1d6c4dbfad62ed3135c0`
- Photoshop: `0fe5bc2cd1d3f273741f5b6abecc82174f6a60a49a28db1e6611abcec1a96975`

## Official runtime readiness blocker

[dcc-mcp-runtime v0.2.0](https://github.com/dcc-mcp/dcc-mcp-runtime/releases/tag/v0.2.0)
publishes a 7,466-byte `py3-none-any` wheel, 9,982-byte sdist and manifests/docs.
The release has no platform CPython runtime executable/archive. Its
[manifest](https://github.com/dcc-mcp/dcc-mcp-runtime/blob/3a54f666c4283bab160dbab3ac90630c9ed39087/runtime/manifest.json)
still declares version `0.1.0`, Python 3.11 / `cp311-win_amd64`, Windows x86-64,
and null runtime SHA/signature. Adapter example manifests carry zero wheel
hashes. Those are templates, not trustworthy release identities. The current
[release workflow](https://github.com/dcc-mcp/dcc-mcp-runtime/blob/3a54f666c4283bab160dbab3ac90630c9ed39087/.github/workflows/release.yml)
builds Python wheel/sdist artifacts, not the PyOxidizer executable.

The existing Core CLI source inspected at the catalog commit does not establish
a complete installer/resolver for this official Python runtime. Its host install
commands and optional skill-runtime descriptors must not be presented as that
missing lifecycle. The runtime package exposes handshake and typed lifecycle
planning, but its presence alone cannot launch an external adapter without Python.

No adapter migration, runtime installation, release, fabricated hashes or
percentage-savings claim is part of this audit. Next: build and validate one
real compatible official runtime target, then migrate a representative external
adapter under its owner before expanding the rollout.

## Adapter execution inventory

| Adapter | Actual Python boundary | Mandatory non-Core requirements |
|---|---|---|
| [dcc-mcp-kdenlive](https://github.com/dcc-mcp/dcc-mcp-kdenlive/blob/5a83cbad7c987e32b86a5314996951ac91311c3b/src/dcc_mcp_kdenlive/server.py) | external python cli or bridge | defusedxml>=0.7.1; psutil>=5.9 |
| [dcc-mcp-PowerPoint](https://github.com/dcc-mcp/dcc-mcp-PowerPoint/blob/451bab3e9df0edad350448a1fcc614415381380e/src/dcc_mcp_powerpoint/_standalone_entry.py) | external python office bridge | None declared |
| [dcc-mcp-maya](https://github.com/dcc-mcp/dcc-mcp-maya/blob/75c1cff038a8192fd5b8cb082f3cac94c7468b92/README.md) | host python plus native sidecar | packaging>=21.3 |
| [dcc-mcp-blender](https://github.com/dcc-mcp/dcc-mcp-blender/blob/f8adfbe1236bcb3085913f9df4877f918f1cca9d/src/dcc_mcp_blender/server.py) | host python embedded | None declared |
| [dcc-mcp-houdini](https://github.com/dcc-mcp/dcc-mcp-houdini/blob/24bc004fb2ee2fb3d3f338cb6b058093cef586ed/src/dcc_mcp_houdini/server.py) | host python embedded | None declared |
| [dcc-mcp-3dsmax](https://github.com/dcc-mcp/dcc-mcp-3dsmax/blob/bbf64cca1257314f3b94418189a36a1e76a408bc/src/dcc_mcp_3dsmax/max_bootstrap.py) | host python plus native sidecar | None declared |
| [dcc-mcp-photoshop](https://github.com/dcc-mcp/dcc-mcp-photoshop/blob/11ad175b94f478e0d303583821980010e873e636/src/dcc_mcp_photoshop/server.py) | external python adobe bridge | adobepy==0.6.2; websockets>=12.0 |
| [dcc-mcp-nuke](https://github.com/dcc-mcp/dcc-mcp-nuke/blob/7354b9c3526b8594d0b0cbdf8d50e0d14f75e775/src/dcc_mcp_nuke/server.py) | host python embedded | None declared |
| [dcc-mcp-unreal](https://github.com/dcc-mcp/dcc-mcp-unreal/blob/afd3408767c72d63db85615e89f60caad8175069/src/dcc_mcp_unreal/_standalone_entry.py) | host python embedded or external native sidecar | None declared |
| [dcc-mcp-liquigen](https://github.com/dcc-mcp/dcc-mcp-liquigen/blob/79cdd21b61c7dcf2a4ba7cc0e583bcbc46f1806f/src/dcc_mcp_liquigen/server.py) | external python native bridge | None declared |
| [dcc-mcp-zbrush](https://github.com/dcc-mcp/dcc-mcp-zbrush/blob/931190e4bfe2cc9d5ad933494a0a5c86001dda40/src/dcc_mcp_zbrush/cli.py) | external python with host python plugin | None declared |
| [dcc-mcp-premiere](https://github.com/dcc-mcp/dcc-mcp-premiere/blob/236bfaa4f62862ce3f0c7f747e58bfe803a14e27/src/dcc_mcp_premiere/server.py) | external python adobe bridge | adobepy>=0.6.2,<1.0.0 |
| [dcc-mcp-aftereffects](https://github.com/dcc-mcp/dcc-mcp-aftereffects/blob/f33a2461732344993e0baaa3ddb48c3f1f550bcb/src/dcc_mcp_aftereffects/server.py) | external python adobe bridge | adobepy==0.6.2; packaging>=24 |
| [dcc-mcp-illustrator](https://github.com/dcc-mcp/dcc-mcp-illustrator/blob/a58baf7e8745b5aa5136fb17005d0082dd95498d/src/dcc_mcp_illustrator/server.py) | external python adobe bridge | adobepy==0.8.0; packaging>=24 |
| [dcc-mcp-gimp](https://github.com/dcc-mcp/dcc-mcp-gimp/blob/5e1690ef219088499fdd5944e5717b8cfe081566/src/dcc_mcp_gimp/bridge.py) | external python with host python plugin | None declared |
| [dcc-mcp-krita](https://github.com/dcc-mcp/dcc-mcp-krita/blob/89f444aa3db6531718686d974889acd488c78e49/src/dcc_mcp_krita/bridge.py) | external python with host python plugin | None declared |
| [dcc-mcp-katana](https://github.com/dcc-mcp/dcc-mcp-katana/blob/d69b53c79056ba6ed92a81ba00e15104e123146b/src/dcc_mcp_katana/server.py) | host python embedded | None declared |
| [dcc-mcp-mobu](https://github.com/dcc-mcp/dcc-mcp-mobu/blob/bbdf9b132502835fbcf464df76b0d22224ba8ef6/src/dcc_mcp_mobu/server.py) | host python embedded | None declared |
| [dcc-mcp-renderdoc](https://github.com/dcc-mcp/dcc-mcp-renderdoc/blob/872c234eabfb0b644f34d74a176e68ada6800991/src/dcc_mcp_renderdoc/server.py) | external python with host python worker | None declared |
| [dcc-mcp-obs](https://github.com/dcc-mcp/dcc-mcp-obs/blob/8726cc04ea31e932817fcad83e96366a9a4ee7b9/src/dcc_mcp_obs/server.py) | external python native bridge | psutil>=5.9,<8; websocket-client>=1.8,<2 |
| [dcc-mcp-substance3d-designer](https://github.com/dcc-mcp/dcc-mcp-substance3d-designer/blob/6c0566c9149271ffa72f1703801f8a2c0c5bdb96/src/dcc_mcp_substance3d_designer/server.py) | host python embedded and external offline | None declared |
| [dcc-mcp-substance3d-painter](https://github.com/dcc-mcp/dcc-mcp-substance3d-painter/blob/40e9ebecba8e40d71186452d20e1708475cbc54a/src/dcc_mcp_substance3d_painter/server.py) | host python embedded | None declared |
| [dcc-mcp-godot](https://github.com/dcc-mcp/dcc-mcp-godot/blob/f55f364b294483e1122eb874a69e469cca05b35b/src/dcc_mcp_godot/bridge.py) | external python native bridge | websockets>=12; Pillow>=10 |
| [dcc-mcp-unity](https://github.com/dcc-mcp/dcc-mcp-unity/blob/3fd2af312d80062ab12c0026591a5df14d68194f/src/dcc_mcp_unity/_standalone_entry.py) | external python native bridge | websockets>=12 |
| [dcc-mcp-marmoset](https://github.com/dcc-mcp/dcc-mcp-marmoset/blob/dfe015455cae7a38e85fa0ade8452740c59fb834/src/dcc_mcp_marmoset/toolbag_plugin/__main__.py) | external python with host python plugin | None declared |
| [dcc-mcp-openscad](https://github.com/dcc-mcp/dcc-mcp-openscad/blob/bdb4e81c47520bd2783575f7510c65aff9722e92/src/dcc_mcp_openscad/server.py) | external python cli | importlib-metadata>=4.13,<7; python_version<'3.8' |
| [dcc-mcp-freecad](https://github.com/dcc-mcp/dcc-mcp-freecad/blob/3cebf96e03e52204f56c73a989181f4c112b9a44/src/dcc_mcp_freecad/bridge.py) | external python with host python worker | None declared |
| [dcc-mcp-cinema4d](https://github.com/dcc-mcp/dcc-mcp-cinema4d/blob/55269d87cdbd5c342b071be7ae0de712cfc694d5/src/dcc_mcp_cinema4d/bridge.py) | external python with host python worker | None declared |
| [dcc-mcp-comfyui](https://github.com/dcc-mcp/dcc-mcp-comfyui/blob/ec7f230ce72dbd29b1aa89a7c51d31a4a60cf709/src/dcc_mcp_comfyui/server.py) | external python http | httpx>=0.25.0 |
| [dcc-mcp-mari](https://github.com/dcc-mcp/dcc-mcp-mari/blob/64f1212de37af2588c661d7c6d19a6c77f4bf232/src/dcc_mcp_mari/mari_plugin/runtime.py) | external python with host python plugin | None declared |
| [dcc-mcp-sketchup](https://github.com/dcc-mcp/dcc-mcp-sketchup/blob/b46b947fef7d09f1c144b2329909f631d02e5be6/src/dcc_mcp_sketchup/bridge.py) | external python native bridge | None declared |
| [dcc-mcp-touchdesigner](https://github.com/dcc-mcp/dcc-mcp-touchdesigner/blob/a6affd188aba9b82349113ae20dd589833b87784/src/dcc_mcp_touchdesigner/server.py) | host python embedded | None declared |
| [dcc-mcp-shogun](https://github.com/dcc-mcp/dcc-mcp-shogun/blob/e7461842f83b579f5654374a7fcd99ce6a95f77f/src/dcc_mcp_shogun/sdk.py) | external python vendor sdk | None declared |
| [dcc-mcp-tiled](https://github.com/dcc-mcp/dcc-mcp-tiled/blob/6351eb5820b4c50009d29173451c726cea293250/src/dcc_mcp_tiled/server.py) | external python cli | None declared |
| [dcc-mcp-material-maker](https://github.com/dcc-mcp/dcc-mcp-material-maker/blob/77082cfc2666dd1a965594cc35560073c5c45f55/src/dcc_mcp_material_maker/server.py) | external python cli | None declared |
| [dcc-mcp-wwise](https://github.com/dcc-mcp/dcc-mcp-wwise/blob/ddc3e31b3187dd2224d5eeb284ed0b4a870a93ac/src/dcc_mcp_wwise/server.py) | external python vendor sdk | packaging>=24,<27; waapi-client>=0.8.1,<0.9 |
| [dcc-mcp-excel](https://github.com/dcc-mcp/dcc-mcp-excel/blob/0fe44fa5fd42f3a4098679561b65088d4f5efd29/src/dcc_mcp_excel/_standalone_entry.py) | external python office bridge | None declared |
| [dcc-mcp-word](https://github.com/dcc-mcp/dcc-mcp-word/blob/8e59aa34b34ac23ffc9c419979c5644046561d22/src/dcc_mcp_word/_standalone_entry.py) | external python office bridge | None declared |
| [dcc-mcp-fpt](https://github.com/dcc-mcp/dcc-mcp-fpt/blob/1238c0b5e9a56410b0ae0bff4926251bddf66e4e/src/dcc_mcp_fpt/server.py) | external python http | None declared |
| [dcc-mcp-openusd](https://github.com/dcc-mcp/dcc-mcp-openusd/blob/7443fc53253673c86bfe32c008a103b8e9ad96d3/src/dcc_mcp_openusd/server.py) | external python sdk | None declared |
| [dcc-mcp-autocad](https://github.com/dcc-mcp/dcc-mcp-autocad/blob/d2acd4859b5a724b6032bd3044684291972a26e2/src/dcc_mcp_autocad/transports/com_transport.py) | external python com or cli | None declared |
| [dcc-mcp-capcut](https://github.com/dcc-mcp/dcc-mcp-capcut/blob/b6f59a03aa420005007ac01042e57f41fae74df3/src/dcc_mcp_capcut/runtime_entry.py) | external python native bridge | None declared |
| [dcc-mcp-epic](https://github.com/dcc-mcp/dcc-mcp-epic/blob/399814cfb1637433156ab8ad49ba8df372bb412a/src/dcc_mcp_epic/runtime.py) | external python mcp sdk | psutil>=5.9,<8.0 |
| [dcc-mcp-gaea](https://github.com/dcc-mcp/dcc-mcp-gaea/blob/401344b885e5a395c6f9ba3ef631484d38ecb5f7/src/dcc_mcp_gaea/server.py) | external python cli | Pillow>=9 |
| [dcc-mcp-openscreen](https://github.com/dcc-mcp/dcc-mcp-openscreen/blob/072f4ea8f2b59cb037ff96e46a9f287484c3c9cd/src/dcc_mcp_openscreen/server.py) | external python native bridge | None declared |
| [dcc-mcp-speedtree](https://github.com/dcc-mcp/dcc-mcp-speedtree/blob/7baacd7836bc928fdd1a5c359a7b77c7f12d9023/src/dcc_mcp_speedtree/server.py) | external python cli | None declared |
| [dcc-mcp-tracy](https://github.com/dcc-mcp/dcc-mcp-tracy/blob/99c7d981c289fa0d4ff24b8600ecf8b368a3ac13/src/dcc_mcp_tracy/server.py) | external python cli | None declared |
