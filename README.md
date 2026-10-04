# Faidlix Blender Add-ons

Faidlix Blender 外掛的集中發布庫。每個外掛都是獨立 Blender Extension，可單獨下載、安裝、更新與移除，不依賴其他套件。

Blender Repository URL：

`https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/index.json`

## 套件

- `faidlix_paint`：Faidlix Paint。
- `faidlix_outliner`：Faidlix Outliner 階層選取與批次顯示控制。
- `faidlix_weight`：Faidlix Weight 選取點權重鏡射與左右名稱對應。
- `faidlix_manager`：選配的「全部更新」管理器。

安裝 Manager 不是使用其他外掛的前提。Manager 只會更新已安裝的 Faidlix 套件，不會自動安裝其他外掛。

## 目錄

- `addons/<AddonName>/`：各外掛的獨立原始碼、manifest 與測試。
- `repository/`：可被 Blender 直接使用的獨立 ZIP 與共用索引。
- `CONTRIBUTING.md`：其他外掛的搬移與發布規範。
