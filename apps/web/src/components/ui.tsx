import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Check, Copy, AlertCircle, ChevronRight, Loader2 } from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api';

export function useResource<T>(path:string, poll=false) { return useQuery({queryKey:[path], queryFn:({signal})=>api<T>(path,{signal}), enabled:!!path, refetchInterval:poll ? 4000 : false}); }
export function Status({value}:{value:string}) {return <span className={`status ${value}`}><i aria-hidden="true"/>{value.replaceAll('_',' ')}</span>}
export function ErrorMessage({error}:{error:unknown}) {return error ? <div className="error" role="alert"><AlertCircle size={16}/>{error instanceof Error ? error.message : String(error)}</div> : null}
export function Loading() {return <div className="loading" role="status"><Loader2 size={18} className="spin"/> Loading…</div>}
export function Empty({title,children}:{title:string;children?:ReactNode}) {return <div className="empty"><ChevronRight size={22}/><h3>{title}</h3><div>{children}</div></div>}
export function Header({title,subtitle,actions}:{title:string;subtitle?:string;actions?:ReactNode}) {return <header className="page-header"><div><h1>{title}</h1>{subtitle&&<p>{subtitle}</p>}</div><div className="actions">{actions}</div></header>}
export function CopyButton({value,label='Copy'}:{value:string;label?:string}) {const [done,setDone]=useState(false);return <button type="button" className="quiet small" aria-label={label} onClick={()=>navigator.clipboard.writeText(value).then(()=>{setDone(true);setTimeout(()=>setDone(false),1500)})}>{done?<Check size={14}/>:<Copy size={14}/>} {done?'Copied':label}</button>}
export function Json({value}:{value:unknown}) {return <pre className="code">{JSON.stringify(value,null,2)}</pre>}
export function Code({children}:{children:string}) {return <div className="code-wrap"><CopyButton value={children}/><pre className="code">{children}</pre></div>}
export function Table({headers,children}:{headers:string[];children:ReactNode}) {return <div className="table-scroll" tabIndex={0} role="region" aria-label="Data table"><table><thead><tr>{headers.map(h=><th key={h}>{h}</th>)}</tr></thead><tbody>{children}</tbody></table></div>}
export function Dialog({title,open,onClose,children}:{title:string;open:boolean;onClose:()=>void;children:ReactNode}) {const ref=useRef<HTMLDialogElement>(null);useEffect(()=>{if(open){ref.current?.showModal();}else{ref.current?.close();}},[open]);return <dialog ref={ref} aria-label={title} onCancel={onClose} onClick={e=>{if(e.target===ref.current)onClose()}}><div className="dialog-head"><h2>{title}</h2><button className="quiet" onClick={onClose} aria-label="Close dialog">×</button></div>{children}</dialog>}
export function Download({path,name,label='Export JSON'}:{path:string;name:string;label?:string}) {return <button className="quiet" onClick={async()=>{const value=await api<unknown>(path);downloadFile(name,JSON.stringify(value,null,2))}}>{label}</button>}
export function downloadFile(name:string,value:string){const url=URL.createObjectURL(new Blob([value],{type:'application/json'}));const link=document.createElement('a');link.href=url;link.download=name;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
export function time(value:string|null|undefined) {return value?new Date(value).toLocaleString():'—'}
export function number(value:number|undefined){return value===undefined?'—':new Intl.NumberFormat(undefined,{maximumSignificantDigits:6}).format(value)}
