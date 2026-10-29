export function notebookExportIssue(pages:{page:number;loaded:boolean;status:string;storageError:string}[]):string{
  const page=pages.find(row=>!row.loaded||row.status!=='saved'||row.storageError);
  return page?`${page.page}쪽의 저장·초안 상태를 확인하세요. 저장 완료 후 PDF를 내보낼 수 있습니다.`:'';
}
