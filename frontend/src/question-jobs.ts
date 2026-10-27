type QuestionScope={session_id?:string|null;course_id?:string|null;mode?:string;lecture_ids?:string[];asset_id?:string|null;page?:number|null;document_sha256?:string|null};

export function sameQuestionContext(request:{prompt?:string;scope?:QuestionScope},prompt:string,scope?:QuestionScope){
  if(!scope||!request.scope||request.prompt!==prompt)return false;
  return (['session_id','course_id','mode','asset_id','page','document_sha256'] as const).every(key=>(request.scope![key]??null)===(scope[key]??null))
    &&JSON.stringify(request.scope.lecture_ids??[])===JSON.stringify(scope.lecture_ids??[]);
}
