# Faidlix Manager

Manager 是 Faidlix Blender 外掛共通功能的唯一實作位置。目前包含固定在側邊欄頂端、無標題且不可摺疊的「全部更新」控制列，以及更新佇列、進度與完成狀態。

更新來源比對會忽略 `?cache=...` 等查詢參數，並優先使用 Manager 實際安裝所在的 repository module，避免重複或空白來源讓按鈕錯誤消失。

其他外掛不得複製共通 Operator／Panel。外掛新增、改名或調整共通能力時，必須同步更新 `addon_registry.json`；Manager 只會對登錄且已安裝的套件執行共通功能。

選配的 Faidlix Blender 外掛管理器。在 3D View 的 `Faidlix` 側邊欄提供唯一的「全部更新」按鈕。

管理器只會更新已安裝且有新版本的 Faidlix 套件，不會安裝使用者沒有選擇的外掛。所有外掛都能在不安裝 Manager 的情況下單獨下載、更新與移除。
