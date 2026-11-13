// Storage restrictions must not prevent login or editing.
const fallback = new Map();
export let storageUnavailable = false;
export function readStorage(kind, key){
  try{return window[kind].getItem(key);}catch{storageUnavailable=true;return fallback.get(kind+key)??null;}
}
export function writeStorage(kind, key, value){
  fallback.set(kind+key,String(value));
  try{window[kind].setItem(key,value);}catch{storageUnavailable=true;}
}
export function removeStorage(kind, key){
  fallback.delete(kind+key);
  try{window[kind].removeItem(key);}catch{storageUnavailable=true;}
}
