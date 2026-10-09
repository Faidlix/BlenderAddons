# Faidlix Blender Add-ons

Faidlix Blender 外掛的集中發布庫。每個外掛都是獨立 Blender Extension，可單獨下載、安裝、更新與移除，不依賴其他套件。

Blender Repository URL：

`https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/index.json`

## 套件

點擊外掛名稱即可直接下載目前正式 ZIP：

- [Blander Peferance 1.1.0](https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/blander_peferance-1.1.0.zip)：保留使用者介面預設值，並快速切換繁體中文／原語系。
- [Faidlix Texture Marge 1.5.8](https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/blander_texture_marge-1.5.8.zip)：貼圖通道合併與材質串接。
- [Faidlix BakeMap 2.3.11](https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/faidlix_bakemap-2.3.11.zip)：材質資訊烘焙。
- [Faidlix Bone Remap 0.6.18](https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/faidlix_bone_remap-0.6.18.zip)：批次骨架動畫重定向。
- [Faidlix_Fbx ZipExporter 1.8.3](https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/faidlix_fbx_zip_exporter-1.8.3.zip)：選擇 Actions 與材質貼圖後輸出 FBX ZIP。
- [Faidlix Manager 1.1.6](https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/faidlix_manager-1.1.6.zip)：選配的共通功能與固定於側邊欄頂端的「全部更新」控制列。
- [Faidlix_Outliner 0.2.17](https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/faidlix_outliner-0.2.17.zip)：階層選取與批次顯示控制。
- [Faidlix Paint 0.4.8](https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/faidlix_paint-0.4.8.zip)：整層、遮罩與 UV 島填色。
- [Faidlix_Weight 1.3.0](https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/faidlix_weight-1.3.0.zip)：選取點權重鏡射與左右名稱對應。

- [Faidlix_BatchCleanKey 1.3.2](https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/faidlix_batch_clean_key-1.3.2.zip)：依選定骨骼，跨 Action 批次刪除、清理與縮減 Key。

安裝 Manager 不是使用其他外掛的前提。Manager 只會更新已安裝的 Faidlix 套件，不會自動安裝其他外掛。

## 目錄

- `addons/<AddonName>/`：各外掛的獨立原始碼、manifest 與測試。
- `repository/`：可被 Blender 直接使用的獨立 ZIP 與共用索引。
- `CONTRIBUTING.md`：其他外掛的搬移與發布規範。
