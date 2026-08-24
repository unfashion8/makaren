# KOKOROE art direction

KOKOROEの作品は、鑑定結果を図解したポスターではなく、鑑賞に耐える一枚の抽象絵画として設計する。
内部計算値は造形方針を決めるためだけに使い、画像・鑑定書・レビュー画面には表示しない。

## 研究から抽出した造形原理

| 系譜 | 参照した代表例 | 実装する一般原理 |
|---|---|---|
| アクション／オールオーバー | Jackson Pollock、Lee Krasner、Willem de Kooning | 身体の軌跡、重力、速度差、全画面の活性、線の重なりを制作時間の記録として扱う |
| カラーフィールド | Mark Rothko、Barnett Newman、Clyfford Still | 大きな色面、柔らかな境界、色の圧力、没入するスケール、内側から現れる光 |
| ステイン | Helen Frankenthaler、Morris Louis | 絵具と支持体の一体化、浸透、滲み、溜まり、偶然と制御の往復 |
| 抒情的抽象／東西の交差 | Zao Wou-Ki、Chu Teh-Chun、Art Informel | 気象のような奥行き、書的な速度、濃淡、空気、集中と拡散、東アジアの余白感覚 |
| 精神的・幾何学的抽象 | Wassily Kandinsky、Hilma af Klint、Kazimir Malevich、Piet Mondrian | 比例、反復、緊張、抽象記号、形と色の心理作用。ただし図解や固定シンボルにはしない |
| 還元／反復 | Agnes Martin、Ad Reinhardt、単色画の系譜 | 微差、静けさ、反復、手作業の揺らぎ、見る時間、最小限の手段による密度 |
| 具体美術 | Gutai Art Association | 絵具・紙・布・水・重力など物質自体の振る舞い、身体行為、破壊と修復、偶発性 |
| もの派／関係の美学 | Mono-ha、Lee Ufan | 物・余白・場所・鑑賞者の関係、少数の出来事、間、痕跡、時間の通過 |
| 物質・表面・光 | Pierre Soulages、Alberto Burri、Antoni Tàpies、現代のプロセス絵画 | インパスト、擦過、亀裂、煤、繊維、反射、マットと光沢、表面を意味の担い手にする |

この一覧は作風を模倣するためのものではない。作品生成時には作家名をプロンプトへ渡さず、上記の原理を再構成する。

## 平面思想と物質的な奥行き

思想的な参照軸として、村上隆が論じ実践してきたスーパーフラットの、遠近法的な上下関係を平らにする画面、高級文化と大衆文化の序列を問い直す視点、表層そのものを意味の場にする考え方を研究対象に含める。ただし、キャラクター、花、輪郭、配色など、村上隆の識別可能な作風やモチーフは模倣しない。

KOKOROEでは、画面の思想的な平面性と、絵具の物質的な奥行きを両立させる。前景／背景を単純な遠近法で分けず、透明層、埋没した痕跡、薄い盛り上がり、擦過、溜まり、マットと光沢、絵具層の縁に落ちる微細な影によって、見る距離で変化する浅いレリーフを構成する。浮遊するCG物体やデジタルな押し出し効果は使わない。

## 額装・印刷に耐える基準

- 2〜3メートル離れても画面全体の重力と視線経路が保たれる
- 20センチまで近づくと、絵肌、下層、温度差、擦過の新しい情報が現れる
- 大・中・小の三つのスケールが共存し、壁紙やホテル装飾のような均一性を避ける
- 暗部を潰さず、高彩度部を一色に飽和させず、印刷時にも階調と色差を分離する
- 外周5%は裁ち落とし安全域とし、重要な出来事を端に依存させない
- 承認後のプリントマスターでは構図・色・トリミングを変えず、物質感、階調、輪郭、微細な層だけを高精細化する

## 必須構成要素

1. 画面の重力と視線経路
2. 密度の偏りと有効な余白
3. 大・中・小のスケール階層
4. 身振りの速度、圧力、方向、停止
5. 染み、擦れ、削り、盛り上がりなどの物質性
6. 透明層と不透明層がつくる時間的奥行き
7. ハード・ソフト・消失・断裂を含むエッジの多様性
8. 色相だけでなく、明度、彩度、温度、濁りの関係
9. 反復と微差、偶然と制御の比率
10. 支持体の繊維や下地が残す抵抗
11. 完成形の中に残る修正跡と埋没した痕跡
12. 一つの読みへ固定しない曖昧さ

## 禁止する画面

- 円・矩形・直線を均等に並べた図解
- 半透明図形を重ねただけのベクター画像
- 中央の円環、マンダラ、標章のような構図
- すべての要素が同じ強さで主張する画面
- 数値表、評価指標、説明文、題名、署名を画像内に配置すること
- 作家名を指定した模倣、既存作品の再現

## 主な調査資料

- MoMA, Jackson Pollock and all-over/action painting: https://www.moma.org/artists/4675-jackson-pollock
- The Met, Abstract Expressionism: https://www.metmuseum.org/essays/abstract-expressionism
- MoMA, Helen Frankenthaler and soak-stain: https://www.moma.org/artists/1974-helen-frankenthaler
- Guggenheim, Lee Ufan: Marking Infinity: https://web.guggenheim.org/exhibitions/leeufan/overview/
- Guggenheim, Agnes Martin: https://www.guggenheim.org/exhibition/agnes-martin
- Guggenheim, Gutai: Splendid Playground: https://www.guggenheim.org/exhibition/gutai-splendid-playground
- Musée d'Art Moderne de Paris, Zao Wou-Ki: https://www.mam.paris.fr/en/node/912
- Guggenheim, Hilma af Klint: Paintings for the Future: https://www.guggenheim.org/exhibition/hilma-af-klint
- MOCA Los Angeles, Superflat: https://www.moca.org/exhibitions/superflat
- Walker Art Center, Superflat as an equal plane for art history, high culture and popular culture: https://www.walkerart.org/press-releases/takashi-murakami-creates-jellyfish-eyes-in-th/
