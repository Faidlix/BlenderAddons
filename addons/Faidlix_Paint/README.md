# Faidlix Paint

Blender 5.2+ 的圖片／材質填色工具。

正式更新來源：`https://raw.githubusercontent.com/Faidlix/BlenderAddons/main/repository/index.json`

本外掛為獨立 Blender Extension，可單獨下載、安裝、更新與移除，不依賴 Faidlix Manager 或其他 Faidlix 外掛。

Paint／Texture Paint 左側工具列最上方的圖示是「線上更新」。點擊後會同步 GitHub，只在有較新版本時下載安裝，保留目前設定且不需要重新啟動 Blender。

## 使用方式

1. 安裝 ZIP 後啟用 **Faidlix Paint**。
2. 進入 3D View 的 **Texture Paint**，或 Image Editor 的 **Paint** 模式。
3. 在左側工具列長按 Blender 原本的 **Fill** 油漆桶圖示。
4. 長按原生 Fill，選擇 **Fill** 或 **UV 島**，在畫布上點一下執行。
5. 顏色可從上方 Tool Settings 調整。

Faidlix Fill 直接使用 Blender 原生筆刷的 **Color、Strength 與 Blend Mode**，也遵循 Unified Color／Unified Strength。介面排列與原生 Texture Paint 相同。

左側工具列最下面另有獨立的 **滴管** 按鈕，也可以按 `C` 呼叫。滴管是一次性的暫時操作，不會切換 Active Tool；取色完成或取消後仍維持原本的 Brush／Fill 與上方 Tool Settings。它使用 Blender Color 欄位旁相同的原生 Eyedropper：可從整個 Blender 畫面取色、拖曳平均、左鍵／Enter 確認、Esc 取消，並遵循 Unified Color。

### UV 島

不需要先選面。選擇 **UV 島** 後直接點擊模型或圖片，外掛會判斷游標命中的面，沿 UV 接縫找出完整島，再填滿該島投影到圖片的範圍。

上方 Tool Settings 的 **外擴邊緣** 可設定向 UV 島外擴張的像素數，預設為 2 px。

### 圖片像素遮罩

長按原生 **Mask** 可選擇：

- **筆刷塗抹**：使用與原生 Brush 相同的圖示、Size、Strength、筆刷資產及快捷控制；一般塗抹加入遮罩，`Ctrl` 塗抹移除遮罩。
- **UV 島填滿**：點一下模型或圖片，將完整 UV 島加入遮罩。
- **Lasso 框選**：拖曳圈選要允許填色的圖片像素。
- **Select Box**：拖曳矩形範圍。
- **Select Circle**：由中心拖出圓形範圍。

各種選取工具一般操作會加入遮罩，按住 `Ctrl` 則從遮罩移除。加選期間顯示黑色半透明範圍，減選顯示白色半透明範圍；Lasso 按住 `Shift` 可拉直目前線段。輕點模型／圖片範圍外會遮罩全部，`Ctrl` 加點擊外部則清空全部遮罩。Texture Paint 中已遮罩部分會以 G255 亮綠色半透明覆蓋顯示；未遮罩部分保持原色。

Mask 第一次使用會建立獨立的 `<圖片名稱>.MaskMap`。Texture Paint 只寫入目前畫面投影範圍；工具列的 **背面** 勾選控制是否連背面投影一併選入。綠色區域代表受遮罩保護，Fill 不會改寫；3D Texture Paint 與 Image Editor Paint 會同步顯示相同綠色覆蓋。

筆刷直接使用 Blender 原生 Texture Paint 引擎在原始 UV 的 MaskMap 上繪製，不建立隱藏 UV，也不執行 Lightmap Pack。綠色預覽直接由 MaskMap 貼圖在 GPU 上繪製，避免以 Python 逐像素掃描和與模型表面閃爍。

工具列的 **邊緣柔化** 以像素控制遮罩邊緣漸層；Fill 會依灰階比例逐漸減弱。**轉黑白圖** 會建立 `<圖片名稱>.MaskBW`，白色代表受保護區、黑色代表可繪製區。

啟用 Blender 的 Texture Paint **面選取遮罩** 時，Mask 筆刷、UV 島、Lasso、Box、Circle 與點擊外部的整體操作只會修改已選取面的 UV 像素。

遮罩會另存成同尺寸的 `<圖片名稱>.MaskMap` 圖片資料；G255 綠色區域受保護，黑色區域允許 Fill，不會直接改寫原始貼圖。

Paint 與 Texture Paint 的 Faidlix 工具選取狀態會雙向同步。

## 目前限制

- 目前暫不支援 UDIM 圖片。
- 透明色採標準 Alpha over 混合。
- UV 超出 0–1 圖片範圍的部分不會填色。
