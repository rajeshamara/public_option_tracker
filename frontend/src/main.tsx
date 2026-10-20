import {useEffect,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {easternDay,daysLeft,relation,matchesDate,groupShortITM,strikeDistance,compareMoneyness,isExpiredForView,DEFAULT_NEAR_STRIKE_RULE,parseNearStrikeRules,resolveNearStrikeRule,type NearStrikeRules,type Position,type Quote} from './tracking';
import './style.css';
type Snapshot={positions:Position[];accounts_count:number;received_at:number};
type Status={connected:boolean;message:string;session_saved?:boolean;retryable?:boolean;demo?:boolean};
type OptionTypeFilterValue='CALL'|'PUT'|'all';
function OptionTypeFilter({value,onChange}:{value:OptionTypeFilterValue;onChange:(value:OptionTypeFilterValue)=>void}){
 return <fieldset className="option-type-filter"><legend className="visually-hidden">Option type</legend>{([['CALL','Call'],['PUT','Put'],['all','All']] as const).map(([type,label])=><label key={type} className={value===type?'active':''}><input type="radio" name="option-type" value={type} checked={value===type} onChange={()=>onChange(type)}/><span>{label}</span></label>)}</fieldset>;
}
const money=(v:number|null|undefined)=>v==null?'—':v.toLocaleString('en-US',{style:'currency',currency:'USD'});
const time=(v:number|null|undefined)=>v?new Date(v).toLocaleTimeString('en-US',{hour:'2-digit',minute:'2-digit',second:'2-digit',timeZone:'America/New_York'})+' ET':'Unavailable';
function App(){
 const [status,setStatus]=useState<Status|null>(null),[snapshot,setSnapshot]=useState<Snapshot|null>(null),[quotes,setQuotes]=useState<Record<string,Quote>>({});
 const [error,setError]=useState(''),[warnings,setWarnings]=useState<string[]>([]),[busy,setBusy]=useState(false),[auto,setAuto]=useState(true),[now,setNow]=useState(Date.now());
 const [refreshSeconds,setRefreshSeconds]=useState(20),[refreshDraft,setRefreshDraft]=useState('20'),[nextRefreshAt,setNextRefreshAt]=useState<number|null>(null),[refreshSchedule,setRefreshSchedule]=useState(0);
 const [nearRules,setNearRules]=useState<NearStrikeRules>({default:DEFAULT_NEAR_STRIKE_RULE}),[rulesBusy,setRulesBusy]=useState(false),[rulesError,setRulesError]=useState(''),[rulesLoadedAt,setRulesLoadedAt]=useState<number|null>(null);
 const [view,setView]=useState('dashboard');
 const [optionType,setOptionType]=useState<OptionTypeFilterValue>('all');
 const [filter,setFilter]=useState('today'),[attention,setAttention]=useState('all'),[symbol,setSymbol]=useState(''),[account,setAccount]=useState('all');
 const [lookup,setLookup]=useState('AAPL'),[lookupQuote,setLookupQuote]=useState<Quote|null>(null),[lookupError,setLookupError]=useState(''),[lookupBusy,setLookupBusy]=useState(false);
 const loading=useRef(false),rulesLoading=useRef(false);const today=easternDay(new Date(now));
 function clearPositions(){setSnapshot(null);setQuotes({});setWarnings([]);setLookupQuote(null);}
 async function api(path:string,options?:RequestInit){
  let r:Response;
  try{r=await fetch(path,{...options,signal:AbortSignal.timeout(45000)});}
  catch{throw new Error('OptionTracker could not reach the backend. Check that it is running, then retry.');}
  let data;
  try{data=await r.json();}catch{throw new Error('OptionTracker received an unreadable response. Please retry.');}
  if(!r.ok){if(r.status===401){setStatus({connected:false,session_saved:false,retryable:false,message:data.detail||'Schwab requires authorization again. Please reconnect.'});clearPositions();}throw new Error(data.detail||'Request failed');}return data;
 }
 async function reloadNearRules(){
  if(rulesLoading.current)return;rulesLoading.current=true;setRulesBusy(true);setRulesError('');
  try{const data=await api('/api/near-strike-rules',{cache:'no-store'});setNearRules(parseNearStrikeRules(data));setRulesLoadedAt(Date.now());}
  catch(e){setRulesError((e as Error).message);}
  finally{rulesLoading.current=false;setRulesBusy(false);}
 }
 async function refresh(){
  if(loading.current)return;loading.current=true;setBusy(true);setNextRefreshAt(null);setError('');
  try{
   let connection:Status;
   try{connection=await api('/api/status');}
   catch(e){setStatus(s=>({demo:s?.demo,connected:false,session_saved:s?.session_saved||s?.connected,retryable:true,message:(e as Error).message}));return;}
   setStatus(connection);
   if(!connection.connected){if(!connection.session_saved)clearPositions();return;}
   const data:Snapshot=await api('/api/positions');setSnapshot(data);
   const symbols=[...new Set(data.positions.map(p=>p.underlying).filter((s):s is string=>!!s))];
   const fresh:Record<string,Quote>={};const failures:string[]=[];
   for(let i=0;i<symbols.length;i+=4){await Promise.all(symbols.slice(i,i+4).map(async symbol=>{try{fresh[symbol]=await api('/api/quote?symbol='+encodeURIComponent(symbol));}catch{failures.push(symbol);}}));}
   setQuotes(fresh);setWarnings(failures);setNow(Date.now());
  }catch(e){setError((e as Error).message+' Any previously loaded positions are not refreshed.');}
  finally{loading.current=false;setBusy(false);}
 }
 useEffect(()=>{const result=new URLSearchParams(location.search).get('connection');if(result)history.replaceState({},'','/');void refresh().then(()=>{if(result==='failed')setError('Authorization did not complete. Reconnect Schwab.');});},[]);
 useEffect(()=>{void reloadNearRules();},[]);
 useEffect(()=>{if(status?.demo)setLookup('DEMO');},[status?.demo]);
 useEffect(()=>{const timer=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(timer);},[]);
 useEffect(()=>{
  if(!auto||busy||(!status?.connected&&!status?.retryable)){setNextRefreshAt(null);return;}
  // Wait a full interval after completion; slower requests must never overlap.
  const started=Date.now();setNow(started);setNextRefreshAt(started+refreshSeconds*1000);
  const timer=setTimeout(()=>void refresh(),refreshSeconds*1000);
  return()=>clearTimeout(timer);
 },[auto,busy,status?.connected,status?.retryable,refreshSeconds,refreshSchedule]);
 function applyRefreshInterval(){
  const seconds=Number(refreshDraft);
  if(!Number.isInteger(seconds)||seconds<1||seconds>3600)return;
  setRefreshSeconds(seconds);setRefreshDraft(String(seconds));setRefreshSchedule(n=>n+1);
 }
 async function connect(){setBusy(true);setError('');try{const data=await api('/api/connect',{method:'POST',headers:{'X-OptionTracker':'1'}});location.assign(data.url);}catch(e){setError((e as Error).message);setBusy(false);}}
 async function getQuote(){setLookupBusy(true);setLookupError('');try{setLookupQuote(await api('/api/quote?symbol='+encodeURIComponent(lookup)));}catch(e){setLookupError((e as Error).message);setLookupQuote(null);}finally{setLookupBusy(false);}}
 const allRows=(snapshot?.positions||[]).map(p=>({...p,days:daysLeft(p.expiration,today),q:p.underlying?quotes[p.underlying]:undefined,...relation(p,p.underlying?quotes[p.underlying]:undefined,resolveNearStrikeRule(nearRules,p.underlying))}));
 const activeRows=allRows.filter(p=>!isExpiredForView(p.expiration,new Date(now)));
 const matchesOptionType=(p:Position)=>optionType==='all'||p.type===optionType;
 const rows=activeRows.filter(matchesOptionType);
 const expiredRows=allRows.filter(p=>matchesOptionType(p)&&isExpiredForView(p.expiration,new Date(now))).sort((a,b)=>(b.expiration||'').localeCompare(a.expiration||'')||compareMoneyness(a,b));
 const optionTypeLabel=optionType==='all'?'':optionType.toLowerCase()+' ';
 const matchingRows=rows.filter(p=>matchesDate(p.days,filter)&&(attention==='all'||attention==='near'&&p.near||attention===p.label)&&(account==='all'||p.account===account));
 // Apply the other dashboard filters before building choices, so every symbol has matching positions.
 const symbols=[...new Set(matchingRows.map(p=>p.underlying||p.symbol))].sort((a,b)=>a.localeCompare(b));
 const symbolAvailable=!symbol||symbols.includes(symbol);
 useEffect(()=>{if(!symbolAvailable)setSymbol('');},[symbolAvailable]);
 const visible=matchingRows.filter(p=>!symbol||!symbolAvailable||(p.underlying||p.symbol)===symbol).sort(compareMoneyness);
 const counts={today:rows.filter(p=>p.days===0).length,soon:rows.filter(p=>p.days!==null&&p.days>=1&&p.days<=3).length,itm:rows.filter(p=>p.days===0&&p.label==='ITM').length};
 const groups=groupShortITM(rows);
 const shortUnknown=rows.filter(p=>p.side==='Short'&&(p.label==='Unknown'||p.days===null)).length;
 const defaultNearRule=resolveNearStrikeRule(nearRules,null);
 const defaultNearLabel=defaultNearRule.use==='$'?`$${defaultNearRule['$']}`:`${defaultNearRule['%']}%`;
 const hasNearOverrides=Object.entries(nearRules).some(([symbol,rule])=>symbol!=='default'&&(rule.use!==defaultNearRule.use||rule[rule.use]!==defaultNearRule[defaultNearRule.use]));
 const nearSummary=hasNearOverrides?`Near strike: per-stock rules · ${defaultNearLabel} default`:`Near strike: within ${defaultNearLabel}`;
 function renderTable(items:typeof rows,sortedDistance=false){return (<div className="table-wrap"><table><thead><tr>{['Underlying / contract','Account','Side','Qty','Expiration','Days','Strike','Stock last','Moneyness',...(sortedDistance?['Strike − stock ($)']:[]),'Distance %','Price time (ET)'].map(h=><th key={h} title={h==='Distance %'?'Percentage move from the current stock price to the strike. Positive means a rise; negative means a fall.':undefined} aria-sort={sortedDistance&&h==='Moneyness'?'other':undefined}>{h}</th>)}</tr></thead><tbody>{items.map((p,i)=>{const sd=strikeDistance(p.strike,p.q?.last);const old=!p.q?.trade_time||now-p.q.trade_time>120000;return <tr key={p.account+p.symbol+p.side+i} className={p.days===0&&p.label==='ITM'?'urgent':p.near?'near-row':''}><td><strong>{p.underlying||'Unknown'} <span className="contract-type">{p.type||'OPTION'}</span></strong><small title={p.description}>{p.symbol}</small></td><td>{p.account}</td><td><span className={'side '+p.side.toLowerCase()}>{p.side}</span></td><td>{p.quantity}</td><td>{p.expiration||'Unknown'}</td><td>{p.days===0?<b className="today">Today</b>:p.days??'—'}</td><td>{money(p.strike)}</td><td>{money(p.q?.last)}</td><td><span className={'badge '+p.label.toLowerCase()}>{p.label}</span>{p.near&&<small className="near-threshold" title="Applied near-strike threshold">Near strike · ≤ {p.nearThreshold}</small>}</td>{sortedDistance?<><td>{sd.dollars==null?'—':`${sd.dollars>0?'+':''}${money(sd.dollars)}`}</td><td>{sd.percent==null?'—':`${sd.percent>0?'+':''}${sd.percent.toFixed(2)}%`}</td></>:<td>{p.distance==null?'—':`${p.distance>0?'+':''}${p.distance.toFixed(2)}%`}</td>}<td>{time(p.q?.trade_time)}<small>{p.q?(p.q.realtime===false?'Delayed · ':p.q.realtime!==true?'Delay unknown · ':'')+(old?'Old / market closed':'Recent last trade'):'No quote'}</small></td></tr>;})}</tbody></table></div>);}
 const stale=!!snapshot&&now-snapshot.received_at>120000;
 const refreshMessage=busy?(status?.connected?'Refreshing…':'Checking connection…'):!auto?'Auto refresh paused':!status?.connected&&!status?.retryable?'Waiting for connection':nextRefreshAt===null?'Scheduling next refresh…':`Next refresh in ${Math.max(0,Math.ceil((nextRefreshAt-now)/1000))}s`;
 function select(f:string,a='all'){setView('all');setFilter(f);setAttention(a);setSymbol('');setAccount('all');}
 return <main>
  <header><div className="brand">OT</div><div><strong>OptionTracker</strong><small>Options expiration dashboard</small></div><div className="header-actions"><span className={'badge '+(status?.demo?'demo-badge':status?.connected?'good':'')}>{status?.demo?'Synthetic demo':status?.connected?'Schwab connected':!status?'Checking connection':status.session_saved?'Connection interrupted':status.retryable?'Connection unavailable':'Not connected'}</span>{status&&!status.demo&&<button onClick={connect} disabled={busy}>{status.connected||status.session_saved?'Reconnect':'Connect Schwab'}</button>}</div></header>
  {status?.demo&&<div className="demo-banner" role="status"><strong>Demo mode · fictional data</strong><span>Explore the dashboard with invented contracts and fixed prices. No brokerage connection, credentials, or real account data are used. Dates follow the current Eastern calendar; UNQUOTED demonstrates a missing price.</span></div>}
  <div className="page-title"><div><p className="eyebrow">EXPIRATION MONITOR</p><h1>{view==='dashboard'?'Short ITM · DTE dashboard':view==='expired'?'Expired options':'All positions'}</h1><p className="muted">{today} · Eastern Time · Tracking only</p></div><div className="refresh"><div className="refresh-status"><label><input type="checkbox" checked={auto} onChange={e=>setAuto(e.target.checked)}/> Auto refresh</label><span className="refresh-countdown" role="timer" aria-live="off">{refreshMessage}</span></div><form className="refresh-interval" onSubmit={e=>{e.preventDefault();applyRefreshInterval();}}><label htmlFor="refresh-seconds">Interval (seconds)</label><input id="refresh-seconds" type="number" min="1" max="3600" step="1" required value={refreshDraft} aria-describedby="refresh-hint" onChange={e=>setRefreshDraft(e.target.value)}/><button type="submit">Apply</button></form><button className="primary" disabled={busy} onClick={()=>void refresh()}>{busy?(status?.connected?'Refreshing…':'Checking…'):status?.connected?'Refresh now':'Retry connection'}</button><small id="refresh-hint" className="refresh-hint">{refreshSeconds}s between refreshes · Choose 1–3600 seconds · Resets to 20s on page reload</small></div></div>
  {!status?.connected&&<div className="notice" role="status">{status?.message||'Checking your connection…'}{status?.retryable&&auto?` Retrying automatically with a ${refreshSeconds}-second interval.`:''}</div>}
  {error&&<div className="error" role="alert">{error}</div>}
  {!!warnings.length&&<div className="notice" role="alert">Quotes unavailable: {warnings.join(', ')}. These positions show unknown moneyness.</div>}
  <nav className="view-tabs" aria-label="Dashboard view"><button className={view==='dashboard'?'active':''} aria-pressed={view==='dashboard'} onClick={()=>setView('dashboard')}>DTE / ITM Dashboard</button><button className={view==='all'?'active':''} aria-pressed={view==='all'} onClick={()=>setView('all')}>All Positions</button><button className={view==='expired'?'active':''} aria-pressed={view==='expired'} onClick={()=>setView('expired')}>Expired{snapshot?` (${expiredRows.length})`:''}</button></nav>
  <div className="rules-toolbar"><div><span className="badge" title="Absolute stock-to-strike distance. Percentage rules use the strike price as the denominator.">{nearSummary}</span><small role="status">{rulesBusy?'Loading near-strike.json…':rulesLoadedAt?`near-strike.json loaded ${time(rulesLoadedAt)}`:'Using the default 0.5% rule'}</small></div><div className="rules-actions"><button disabled={rulesBusy} onClick={()=>void reloadNearRules()} title="Reload near-strike.json and recalculate near-strike labels and filters">{rulesBusy?'Loading rules…':'Refresh OTM'}</button>{view!=='all'&&<OptionTypeFilter value={optionType} onChange={setOptionType}/>}</div></div>
  {rulesError&&<div className="error" role="alert">Could not reload near-strike.json: {rulesError} {rulesLoadedAt?'The previously loaded rules remain active.':'Using the default 0.5% threshold.'}</div>}
  {view==='dashboard'?<>
   <div className="dte-summary"><span><strong>{snapshot&&!busy?groups.reduce((n,g)=>n+g.rows.length,0):'—'}</strong> short ITM legs</span><span>{groups.length} expiration sections</span><span>Last refresh: {snapshot?time(snapshot.received_at):'Not loaded'}{busy?' · Refreshing…':stale?' · Stale':''}</span></div>
   <p className="muted dte-note">Short legs only · In the money · Calendar DTE from {today} (Eastern Time). Empty DTE sections are hidden.</p>
   {shortUnknown>0&&<div className="notice">{shortUnknown} short legs have unavailable prices or expiration dates and cannot be classified here. Check All Positions.</div>}
   {groups.map(group=><section className="panel dte-section" key={group.dte} aria-label={'DTE '+group.dte}><div className="panel-title"><div><h2>DTE {group.dte}{group.dte===0?' · Today':''}</h2><p className="muted">{group.rows[0].expiration} · {group.rows.length} short ITM {group.rows.length===1?'leg':'legs'}</p></div><span className="badge itm">Short · ITM</span></div>{renderTable(group.rows)}</section>)}
   {!groups.length&&<section className="panel empty"><h3>{status?.retryable?'Schwab connection is temporarily unavailable':!status?.connected?'Connect Schwab to see short ITM positions':busy?'Loading positions and prices…':!snapshot?'Positions not loaded':`No short ITM ${optionTypeLabel}positions to show`}</h3><p>{status?.retryable?'Retry the connection to load current positions.':snapshot?'Only active short ITM legs appear here. Expiration-day legs move to Expired at 4:00 p.m. Eastern.':'Connect and refresh to load your positions.'}</p><button onClick={()=>setView('all')}>View All Positions</button></section>}
   <p className="table-footer">ITM is based on the underlying’s last trade, including extended-hours trades; check the price timestamp. It does not predict assignment or exercise. Adjusted contracts require separate review.</p>
  </>:view==='expired'?<section className="panel">
   <div className="panel-title"><div><h2>Expired options</h2><p className="muted">{expiredRows.length} legs · Latest expiration first</p></div><span className="badge">4:00 p.m. ET cutoff</span></div>
   <div className="table-footer">Expiration-day legs move here at 4:00 p.m. Eastern. This display rule does not confirm settlement or assignment. Only positions in the current snapshot are shown; this is not a historical archive.</div>
   {renderTable(expiredRows,true)}
   {!expiredRows.length&&<div className="empty"><h3>{!status?.connected?'Connect Schwab to see expired positions':busy?'Loading positions…':`No expired ${optionTypeLabel}positions returned`}</h3><p>Today’s expiring legs move here automatically at 4:00 p.m. Eastern.</p></div>}
   <div className="table-footer">Prices and moneyness use the latest available underlying trade, not the expiration settlement price.</div>
  </section>:<>
  <section className="widgets" aria-label="Position summary">
   <button className={'widget '+(filter==='today'&&attention==='all'?'selected':'')} onClick={()=>select('today')}><span>Expiring today</span><strong>{snapshot?counts.today:'—'}</strong><small>Option legs · view today</small></button>
   <button className="widget" onClick={()=>{select('all');setFilter('next3');}}><span>Next three days</span><strong>{snapshot?counts.soon:'—'}</strong><small>Tomorrow through day 3</small></button>
   <button className={'widget danger '+(attention==='ITM'&&filter==='today'?'selected':'')} onClick={()=>select('today','ITM')}><span>ITM · expiring today</span><strong>{snapshot?counts.itm:'—'}</strong><small>Based on available last trades</small></button>
   <div className="widget sync"><span>Last position refresh</span><strong className="sync-time">{snapshot?time(snapshot.received_at):'Not loaded'}</strong><small>{stale?'Stale · more than 2 minutes old · ':''}{refreshMessage}</small></div>
  </section>
  <section className="panel">
   <div className="panel-title"><div><h2>Option positions</h2><p className="muted">{snapshot?`${rows.length} legs · ${snapshot.accounts_count} ${status?.demo?'demo account':'linked accounts'}`:'Your open option legs will appear here.'}</p></div><span className="badge">{nearSummary}</span></div>
   <div className="toolbar"><div className="tabs" role="group" aria-label="Expiration filter">{[['today','Today'],['tomorrow','Tomorrow'],['soon','Days 2–3'],['later','Later'],['all','All'],...(filter==='next3'?[['next3','Next 3 days']]:[])].map(([f,label])=><button aria-pressed={filter===f} className={filter===f?'active':''} key={f} onClick={()=>setFilter(f)}>{label}</button>)}</div><div className="filters"><OptionTypeFilter value={optionType} onChange={setOptionType}/><select className="symbol-filter" aria-label="Symbol" value={symbol} onChange={e=>setSymbol(e.target.value)}><option value="">All symbols</option>{symbols.map(s=><option value={s} key={s}>{s}</option>)}</select><select aria-label="Account" value={account} onChange={e=>setAccount(e.target.value)}><option value="all">All accounts</option>{[...new Set(activeRows.map(p=>p.account))].map(a=><option key={a}>{a}</option>)}</select><select aria-label="Moneyness" value={attention} onChange={e=>setAttention(e.target.value)}>{[['all','All positions'],['ITM','In the money'],['OTM','Out of the money'],['near','Near strike'],['Unknown','Unknown price']].map(([v,l])=><option value={v} key={v}>{l}</option>)}</select></div></div>
   {renderTable(visible,true)}
   {!visible.length&&<div className="empty"><h3>{!status?.connected?'Connect Schwab to see your positions':busy&&!snapshot?'Loading your positions…':!snapshot?'Positions not loaded':activeRows.length?'No positions match this view':'No open option positions'}</h3><p>{activeRows.length?'Choose All or adjust the filters.':'Your account data stays in this local app.'}</p>{activeRows.length>0&&<button onClick={()=>{setOptionType('all');select('all');}}>Show all positions</button>}</div>}
   <div className="table-footer">Showing {visible.length} of {rows.length} legs. Shorts first, then Longs. Within each side: ITM, then ATM, then OTM, with unknown prices last. Within each moneyness group: expiry days ascending, then absolute Distance % ascending (closest to the strike first for the same expiry). Distance % = (strike − stock price) ÷ stock price × 100. {stale?'Position snapshot is stale. ':''}ITM status uses the underlying’s last trade; it does not predict assignment or exercise. Adjusted contracts require separate review.</div>
  </section>
  </>}
  <section className="panel lookup"><div><h2>Quick quote</h2><p className="muted">{status?.demo?'Demo symbols: DEMO, SAMPLE, FICTION. All prices are fictional.':'Look up any symbol without changing your position filters.'}</p></div><form onSubmit={e=>{e.preventDefault();void getQuote();}}><input aria-label="Quote symbol" value={lookup} onChange={e=>setLookup(e.target.value)} maxLength={20} required/><button disabled={!status?.connected||lookupBusy}>{lookupBusy?'Loading…':'Get quote'}</button></form>{lookupError&&<p className="error" role="alert">{lookupError}</p>}{lookupQuote&&<div className="quote-result"><strong>{lookupQuote.symbol} {money(lookupQuote.last)}</strong><span>Bid {money(lookupQuote.bid)} · Ask {money(lookupQuote.ask)}</span><small>{status?.demo?'Generated':'Trade'} {time(lookupQuote.trade_time)} · {status?.demo?'Synthetic price':lookupQuote.realtime===true?'Real-time entitlement':lookupQuote.realtime===false?'Delayed':'Delay unknown'} · Manual lookup</small></div>}</section>
 </main>;
}
createRoot(document.getElementById('root')!).render(<App/>);
