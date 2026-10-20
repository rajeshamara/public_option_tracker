export type Position = {account:string; symbol:string; description:string; underlying:string|null; type:string|null; expiration:string|null; strike:number|null; side:string; quantity:number};
export type Quote = {symbol:string; last:number|null; bid:number|null; ask:number|null; quote_time:number|null; trade_time:number|null; realtime:boolean|null; received_at:number};
export type NearStrikeRule = {'$':number;'%':number;use:'$'|'%'};
export type NearStrikeRules = Record<string,NearStrikeRule>;
export const DEFAULT_NEAR_STRIKE_RULE:NearStrikeRule = {'$':3,'%':0.5,use:'%'};
export function parseNearStrikeRules(data:unknown):NearStrikeRules{
 if(!data||typeof data!=='object'||Array.isArray(data))throw new Error('Near-strike rules must be an object.');
 if(!Object.hasOwn(data,'default'))throw new Error('Near-strike rules must include a default rule.');
 const rules:NearStrikeRules={};
 for(const [symbol,value] of Object.entries(data)){
  if(!symbol.trim()||symbol!==symbol.trim())throw new Error('Near-strike rule symbols must be nonempty and have no surrounding spaces.');
  const key=symbol==='default'?'default':symbol.toUpperCase();
  if(key==='DEFAULT'||key!=='default'&&!/^[A-Z0-9.$/-]{1,20}$/.test(key)||Object.hasOwn(rules,key))throw new Error(`Duplicate or invalid near-strike rule: ${symbol}.`);
  if(!value||typeof value!=='object'||Array.isArray(value)||Object.keys(value).length!==3||!['$','%','use'].every(name=>Object.hasOwn(value,name)))throw new Error(`Near-strike rule for ${symbol} must contain exactly "$", "%" and "use".`);
  const rule=value as Record<string,unknown>;
  const dollars=rule['$'],percent=rule['%'],use=rule.use;
  if(typeof dollars!=='number'||!Number.isFinite(dollars)||dollars<0||typeof percent!=='number'||!Number.isFinite(percent)||percent<0||(use!=='$'&&use!=='%'))throw new Error(`Near-strike rule for ${symbol} requires nonnegative finite numbers and use must be "$" or "%".`);
  rules[key]={'$':dollars,'%':percent,use};
 }
 return rules;
}
export function resolveNearStrikeRule(rules:NearStrikeRules,underlying:string|null|undefined):NearStrikeRule{
 const symbol=underlying?.trim().toUpperCase();
 return (symbol?rules[symbol]:undefined)||rules.default||DEFAULT_NEAR_STRIKE_RULE;
}
export function easternDay(now:Date){return new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(now);}
export function daysLeft(expiry:string|null,today:string){return expiry ? Math.round((Date.parse(expiry+'T00:00:00Z')-Date.parse(today+'T00:00:00Z'))/86400000):null;}
export function relation(p:Position,q?:Quote,rule:NearStrikeRule=DEFAULT_NEAR_STRIKE_RULE){
 const nearThreshold=rule.use==='$'?`$${rule['$']}`:`${rule['%']}%`;
 if(!q||q.last==null||!Number.isFinite(q.last)||q.last<=0||p.strike==null||!Number.isFinite(p.strike)||p.strike<=0||!['CALL','PUT'].includes(p.type||''))return {label:'Unknown',near:false,distance:null,nearThreshold};
 const distance=strikeDistance(p.strike,q.last).percent;
 const thresholdDollars=rule.use==='$'?rule['$']:p.strike*rule['%']/100;
 // Include the exact boundary despite floating-point subtraction of decimal prices.
 const roundingTolerance=Number.EPSILON*Math.max(q.last,p.strike)*2;
 const near=Math.abs(q.last-p.strike)<=thresholdDollars+roundingTolerance;
 return {label:q.last===p.strike?'ATM':(p.type==='CALL'?q.last>p.strike:q.last<p.strike)?'ITM':'OTM',near,distance,nearThreshold};
}
export function matchesDate(days:number|null,filter:string){return filter==='all'||(filter==='next3'&&days!==null&&days>=1&&days<=3)||(filter==='today'?days===0:filter==='tomorrow'?days===1:filter==='soon'?days!==null&&days>=2&&days<=3:filter==='later'?days!==null&&days>3:false);}

export function groupShortITM<T extends {side:string;label:string;days:number|null}>(rows:T[]):{dte:number;rows:T[]}[]{
 const groups=new Map<number,T[]>();
 for(const row of rows){if(row.side!=='Short'||row.label!=='ITM'||row.days===null||!Number.isInteger(row.days)||row.days<0)continue;
 const group=groups.get(row.days)||[];group.push(row);groups.set(row.days,group);}
 return [...groups.entries()].sort(([a],[b])=>a-b).map(([dte,rows])=>({dte,rows}));
}
export function strikeDistance(strike:number|null,price:number|null|undefined){
 if(strike==null||!Number.isFinite(strike)||strike<=0||price==null||!Number.isFinite(price)||price<=0)return {dollars:null,percent:null};
 const dollars=strike-price;
 return {dollars,percent:dollars/price*100};
}
export function compareDistance(a:number|null,b:number|null){return a===null?(b===null?0:1):b===null?-1:a-b;}
export function compareMoneyness(a:{side:string;label:string;days:number|null;distance:number|null},b:{side:string;label:string;days:number|null;distance:number|null}){
 const sideRank=(p:typeof a)=>p.side==='Short'?0:p.side==='Long'?1:2;
 const sideOrder=sideRank(a)-sideRank(b);
 if(sideOrder!==0)return sideOrder;
 const rank=(p:typeof a)=>p.distance===null||!Number.isFinite(p.distance)?3:p.label==='ITM'?0:p.label==='ATM'?1:p.label==='OTM'?2:3;
 const ar=rank(a),br=rank(b);
 if(ar!==br)return ar-br;
 const aDays=a.days!==null&&Number.isFinite(a.days)?a.days:Infinity;
 const bDays=b.days!==null&&Number.isFinite(b.days)?b.days:Infinity;
 if(aDays!==bDays)return aDays-bDays;
 if(ar===3)return 0;
 return Math.abs(a.distance!)-Math.abs(b.distance!);
}
// User-selected display cutoff, not exchange trading/settlement metadata.
export function isExpiredForView(expiry:string|null,now:Date){
 if(!expiry)return false;
 const today=easternDay(now);
 if(expiry<today)return true;
 if(expiry>today)return false;
 const hour=Number(new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',hour:'2-digit',hourCycle:'h23'}).format(now));
 return hour>=16;
}
