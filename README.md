# aggy


## TODO
- [x] test out valkey
- [x] build docker container for webui
- [x] setup main instance of webui and API
- [x] setup script to allow locally running the webui within docker container with api
- [x] move todo items to github issues
- [x] route testing
- [x] add license
- [x] pagination for any api returning list
- [ ] user interactions (opens, up and down votes)
- [ ] save preview image(s)
- [ ] setup embeddings container
- [ ] generate embeddings text
- [ ] generate embeddings for images
- [ ] train models on user data + embeddings
- [ ] use embeddings to help decide which image would be the best preview image
- [ ] fix reddit albums getting very low res thumbnails
- [ ] de-duplicate posts where possible (same title, picture(maybe based on embeddings?), link after redirects)
- [ ] Add RSS bridge (or similar) to docker compose setup (use this to template rss feeds?)
- [ ] API for templated rss feeds


### Database Design

```mermaid
flowchart TB
    subgraph Legend
        direction LR
        set{{set}}
        sorted_set([sortered set])
        string[string]
        hash>hash]
        list[[list]]
        hash --linked by key-->string
        hash -.linked implicitly.-> sorted_set
    end

    feeds_to_ingest([FEED-KEYS-TO-INGEST]) --feed key--> feed

    subgraph User Space ALL keys prefixed with USER:username_hash:
        user>USER:username_hash]
        user--password--> password_hash[password hash]
        user--username--> username[username]
        user--key-->misc_user_settings[misc user settings]

        categories([CATEGORIES])
        category>CATEGORY:uuid]
        category_embeddings_model[category embeddings model]
        category_name[category name]
        category_feeds{{CATEGORY:uuid:FEEDS}}
        category_items([CATEGORY:uuid:ITEMS])
        feed>CATEGORY:uuid:FEED:name_hash]
        feed_url[url]
        feed_name[name]
        items([FEED:name_hash:ITEMS])


        categories --> category

        category --embeddings model--> category_embeddings_model
        category --name--> category_name
        category -.-> category_items
        category -.-> category_feeds
        category_feeds --> feed
        feed --url--> feed_url
        feed --name--> feed_name
        feed -.-> items

        items -.-> item_state[CATEGORY:hash:ITEM:hash:ITEM_STATE]

    end

    item[ITEM:url_hash]
    item_embeddings>ITEM:url_hash:EMBEDDINGS]
    item_embedding[item embedding]

    items-.->item
    item -.-> item_state
    category_items -.-> item
    category_items -.-> item_embeddings
    item_embeddings --model_name--> item_embedding
    item -.-> item_embeddings
    category_embeddings_model -.-> item_embedding
    users{{USERS}} --> user
    feed_templates{{FEED_TEMPLATES}} --> feed_template[FEED_TEMPLATE:hash]
```
