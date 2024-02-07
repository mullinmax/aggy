# blinder



## TODO
- [ ] make side menu useable
    - [ ] add an edit/delete button/route for feeds
    - [ ] when adding feed suggest categories/autofill
- [ ] pagination
- [ ] add published date, favicon and metadata to items
- [ ] add feed management + stats(opens, % open, new since last open)
- [ ] collect user data (opens, up and down votes)
- [ ] break image collection into seperate microservice
- [ ] create embeddings microservice for text/images
- [ ] create microservice for training models on embeddings and user data
- [ ] find most relevant image on a website using embeddings?
- [ ] fix reddit albums getting very low res thumbnails
- [ ] de-duplicate posts where possible (same title, picture(maybe based on embeddings?), link after redirects)



### Database Design

```mermaid
erDiagram
    item {
        item_id id
        feed_id id
        title string
        body string
        raw_xml string
        ingest_date datetime
    }

    feed {
        feed_id id
        name string
        url string
        source type
        auth string
    }

    score {
        score id
        item_id id
        model_id id
        score float
        confidence float
    }

    model {
        model_id id
        user_id id
        vector_source_id id
        train_date datetime
        tp int
        fp int
        tn int
        fn int
        weights string
    }

    vector_source {
        vector_source_id id
        name string
    }

    vector {
        item_id id
        source id
    }

    activity {
        activity_id id
        user_id id
        action string
        time datetime
    }

    user {
        id id
        name string
        hashed_password string
        write bool
        admin bool
    }

    item }o--|| feed : from
    vector }o--|| vector_source : from
    item ||--o{ vector : describes
    item ||--o{ score : ranks
    score }o--|| model : produces
    model }o--|| user : predicts
    model }o--|| vector_source : trained_by
    item ||--o{ activity : logs
    activity }o--|| user : click

``` 
