# Elang API Reference

## Base URL
```
https://elang.zju.edu.cn:8082/
```

## Authentication
All API requests require:
- Header: `token` - User token from localStorage("user").token
- Header: `X-Requested-With: XMLHttpRequest`
- Header: `Content-Type: application/json`

User info stored in `localStorage.getItem("user")`:
```json
{
  "sid": 284339,
  "token": "9edd1978-93dc-11f0-8dbb-00505699724e",
  "name": "...",
  "userno": "..."
}
```

## Reading Endpoints

### Get Reading Categories
```
POST /subjectCate/gets
Body: {"type_id": 2}
```

### Get Subjects in Category
```
POST /subject/gets
Body: {"cate_id": XX, "type_id": 2}
```

### Get Reading Resources (articles in subject)
```
POST /resources/gets
Body: {"subject_id": XX}
```

### Get User Study Resources (learning history)
```
POST /resources/getUserResourceList
Body: {"subject_id": XX, "sid": YY}
```

### Save Study Progress
```
POST /resources/saveUserStudyResource
Body: {"resources_id": XX, "sid": YY, "log_id": ZZ}
```

### Update Study Progress
```
POST /resources/updateUserStudy
Body: {"log_id": XX, "study_minutes": YY}
```

## Mini Paper (Quiz) Endpoints

### Start Mini Paper
```
GET /paper/startMiniPaper?sid={sid}
Returns: {code: 100, data: {paper_id: XX}}
```

### Get Reading Mini Paper Questions
```
GET /paper/getMiniPaperByRead?sid={sid}&ques_id={ques_id}
Returns: {
  code: 100,
  data: {
    readingPassage: {id, context: "passage text..."},
    questions: {
      questions: [{id, question_text, options, answer}],
      is_check: ""
    }
  }
}
```

### Submit Reading Mini Paper
```
POST /paper/paperReadMiniSubmit
Body: {
  sid: 284339,
  pc_id: "paper_id",
  result: '{"questions":[{"question_id":123,"answer":"A"}]}'
}
```

### Get Mini Paper History
```
GET /paper/getMiniPaperHisList?sid={sid}
```

### Get Mini Paper Report
```
GET /paper/getMiniPaperRow?pc_id={paper_id}
```
