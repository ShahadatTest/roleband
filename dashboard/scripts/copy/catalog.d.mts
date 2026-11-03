export class CopyError extends Error {}
export const camel: (id: string) => string;
export interface Message { id:string;file:string;src:string;pattern:any;node:any;meta:Record<string,string>;terms:Map<string,any> }
export function readLocale(root:string,locale:string):{files:string[];terms:Map<string,any>;messages:Message[];keyed:Set<string>};
export function contract(pattern:any):{display:Set<string>;variables:Set<string>;selectors:Map<string,{numeric:boolean;keys:string[];default:string}>;terms:Set<string>};
export function parity(english:Message,translated:Message):string[];
export function dependencies(msg:Message):Record<string,unknown>;
export function branches(pattern:any,terms:Map<string,any>):string[];
export function semantic(value:any):any;
export function manifestAt(root:string):any;
