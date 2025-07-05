# Fast Danbooru

一个轻量级反向代理服务，简化并代理原生调用，并解决跨域等问题，用于从 [Danbooru](https://danbooru.donmai.us) 获取图片，主要为了配合 Silly Tavern 前端助手设计的。


## ⚙️ 参数说明

| 参数名 | 类型 | 说明 |
|--------|------|------|
| `work_name` | 字符串 | 作品名（自动转为 `copyright:` 标签） |
| `character_name` | 字符串 | 角色名（自动转为 `character:` 标签） |
| `tags[]` | 字符串数组 | 通用标签（AND 逻辑），唯一必填参数 |
| `width` | 整数 | 宽度范围（±100） |
| `select_mode` | 枚举 | 选图方式（基于排序）：`default`, `random`, `score`, `rank` 等 |


## 📡 调用示例

### 示例 1：基本调用
```
GET /image.jpg?tags[]=cat&tags[]=blue_eyes
```
（也支持逗号风格的形式）

### 示例 2：带作品名和角色名
```
GET /image.jpg?work_name=naruto&character_name=sakura&tags[]=fighting
```

### 示例 3：指定宽度并按评分排序
```
GET /image.jpg?tags[]=landscape&width=850&select_mode=score
```

### 示例 4：随机图片
```
GET /image.jpg?tags[]=cute&select_mode=random
```

## 酒馆配置

请参考 [类脑话题](https://discord.com/channels/1134557553011998840/1379737729348145162/1379737729348145162)


## 后续计划

- [ ] 类似于负面标签等方向的图片筛选优化，探索更多 api 功能。
- [ ] 视频模式（确实写完才知道其实是支持视频的）