# Faidlix Bone Remap 0.6.5 驗證紀錄

日期：2026-10-05

## 驗證範圍

- Target：`角色1003.blend`
- 來源：`fairy-new-model.blend` 的 `Fairy_Idle`、`Fairy_Run`
- 來源：`Walk.fbx`、`Idle.fbx`、`Run.fbx`
- 執行版本：安裝於 Blender 5.2 使用者擴充套件目錄的 0.6.5 正式 ZIP
- 所有來源均先自動配骨架、自動縮放、前方軸向／Rest Basis 轉換，再於腳部設定 IK 後批次重定向。

## 結果

- 五個輸出 Action 均包含動態曲線，不再輸出靜止姿勢。
- 兩個建立的腳部 IK 控制骨均為非 Deform。
- 五個輸出的 Root Z 範圍均為 `0.0`，未再持續向下掉落。
- 安裝版載入路徑為 Blender 5.2 的 `extensions/FaidlixBlenderAdd_ons/faidlix_bone_remap`，版號確認為 0.6.5。

| 輸出 | 動態曲線 | 旋轉幅度相似度 | 平均角度誤差 |
| --- | ---: | ---: | ---: |
| fairy-new-model_Fairy_Idle | 42 | 0.903388 | 0.243199° |
| fairy-new-model_Fairy_Run | 152 | 0.643716 | 2.331935° |
| Walk_Walk_N | 55 | 0.497927 | 2.214535° |
| Idle_Idle | 54 | 0.999981 | 0.081954° |
| Run_Run | 65 | 0.932333 | 3.276377° |

相似度是以九個等比例時間點、全部已映射骨頭相對首幀的局部旋轉角度計算 cosine similarity。它可判斷動作節奏／幅度是否被保留，但不等同視覺品質評分。Idle 與 Run 結果高，Fairy Idle 良好；Fairy Run 與 Walk 保留動作但仍受不同骨架比例、IK 與骨頭分布影響，後續若要提高可針對肢體分組權重與 IK 鏈做視覺調校。

## 已知限制

- Blender MCP 的獨立背景執行器未設定 `BLENDER_PATH`，因此正式安裝版回歸改由直接背景 Blender 執行。
- 前景 MCP 連線中的 Blender 是另一份有未儲存修改的檔案，未切換或儲存，避免污染使用者工作。
- Windows 畫面唯讀檢查等待控制核准逾時，未進行任何點擊或畫面操作。
- 使用者指定：之後僅在明確要求操作時控制 Blender，且一次只操作一個實例。
- GitHub 正式推送被安全審核擋下；需使用者明確核准目的地 `https://github.com/Faidlix/BlenderAddons.git` 後才可推送。
