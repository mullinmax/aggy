# blinder



## Sites to support

* [ ] youtube
* [ ] reddit
* [ ] facebook
* [ ] X
* [ ] twitch
* [ ] amazon? (search results)
* [ ] mastadon
* [ ] lemmy
* [ ] instagram
* [ ] tik tok
* [ ] pinterest
* [ ] linkedin
* [ ] Adult media
* [ ] threads





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

## Redis for db?

