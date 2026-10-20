import ts from 'typescript';
import fs from 'node:fs';
import assert from 'node:assert/strict';
const source=ts.transpileModule(fs.readFileSync('src/tracking.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.ES2022,target:ts.ScriptTarget.ES2022}}).outputText;
const {daysLeft,easternDay,relation,matchesDate,DEFAULT_NEAR_STRIKE_RULE,parseNearStrikeRules,resolveNearStrikeRule}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
assert.equal(easternDay(new Date('2026-09-25T02:00:00Z')),'2026-09-24');
assert.equal(daysLeft('2026-09-25','2026-09-24'),1);
assert.equal(daysLeft('2027-01-01','2026-12-31'),1);
assert.equal(daysLeft(null,'2026-09-24'),null);
assert.equal(matchesDate(0,'next3'),false);assert.equal(matchesDate(3,'next3'),true);
assert.equal(matchesDate(1,'soon'),false);assert.equal(matchesDate(2,'soon'),true);
const p={strike:100,type:'CALL'};
assert.equal(relation(p,{last:101}).label,'ITM');assert.equal(relation(p,{last:101}).near,false);
assert.equal(relation({...p,type:'PUT'},{last:101}).label,'OTM');
assert.equal(relation(p,{last:100}).label,'ATM');assert.equal(relation(p,{last:0}).label,'Unknown');
assert.equal(relation(p).label,'Unknown');
console.log('PASS: Eastern dates, exclusive date filters, calls/puts, ATM, near-strike boundary, missing prices');
assert.deepEqual(DEFAULT_NEAR_STRIKE_RULE,{'$':3,'%':0.5,use:'%'});
for(const type of ['CALL','PUT']){
 for(const last of [99.5,100.5])assert.equal(relation({...p,type},{last}).near,true,`${type} includes the 0.5% boundary at ${last}`);
 for(const last of [99.4999,100.5001])assert.equal(relation({...p,type},{last}).near,false,`${type} excludes prices past the 0.5% boundary at ${last}`);
}
assert.equal(relation({strike:350,type:'PUT'},{last:353.27}).near,false,'Synthetic price outside the default 0.5% band');
assert.equal(relation({strike:0.1,type:'CALL'},{last:0.1005}).near,true,'Decimal rounding must not exclude the exact percentage boundary');
assert.equal(relation(p,{last:100.5}).nearThreshold,'0.5%');
assert.equal(relation(p,{last:102.5},{'$':3,'%':0.5,use:'$'}).near,true,'Dollar mode ignores the inactive percentage');
assert.equal(relation(p,{last:104},{'$':3,'%':99,use:'$'}).near,false,'An inactive percentage must not expand the dollar band');
assert.equal(relation(p,{last:102.5},{'$':1,'%':3,use:'%'}).near,true,'Percentage mode ignores the inactive dollars');
for(const last of [97,103])assert.equal(relation(p,{last},{'$':3,'%':0.1,use:'$'}).near,true,'Both dollar boundaries are inclusive');
assert.equal(relation(p,{last:103.001},{'$':3,'%':0.1,use:'$'}).near,false);
assert.equal(relation(p,undefined,{'$':3,'%':0.5,use:'$'}).nearThreshold,'$3');
assert.equal(relation(p).near,false);
assert.equal(relation({...p,strike:Infinity},{last:100}).near,false);
assert.equal(relation({...p,strike:Infinity},{last:100}).label,'Unknown');
assert.equal(relation(p,{last:100},{'$':0,'%':0,use:'%'}).near,true);
assert.equal(relation(p,{last:100.0001},{'$':0,'%':0,use:'%'}).near,false);
console.log('PASS: default 0.5% near-strike band, CALL/PUT and dollar boundaries, active-mode selection, rounding and unavailable values');
const rules=parseNearStrikeRules({default:{'$':2,'%':0.25,use:'%'},avgo:{'$':3,'%':0.5,use:'$'},TSLA:{'$':1,'%':2,use:'%'}});
assert.deepEqual(Object.keys(rules),['default','AVGO','TSLA']);
assert.deepEqual(resolveNearStrikeRule(rules,' avgo '),{'$':3,'%':0.5,use:'$'});
assert.deepEqual(resolveNearStrikeRule(rules,'tsla'),{'$':1,'%':2,use:'%'});
assert.equal(resolveNearStrikeRule(rules,'AAPL'),rules.default);
assert.equal(resolveNearStrikeRule(rules,null),rules.default);
assert.equal(resolveNearStrikeRule({},'AAPL'),DEFAULT_NEAR_STRIKE_RULE);
assert.equal(resolveNearStrikeRule({},undefined),DEFAULT_NEAR_STRIKE_RULE);
assert.equal(relation({strike:350,type:'PUT'},{last:352.5},resolveNearStrikeRule(rules,'AVGO')).near,true);
assert.deepEqual(parseNearStrikeRules({default:{'$':0,'%':0,use:'$'}}).default,{'$':0,'%':0,use:'$'});
const invalidRules=[
 null,[],42,'rules',{},
 {AVGO:DEFAULT_NEAR_STRIKE_RULE},
 {default:null},{default:[]},
 {default:{'$':3,'%':0.5}},
 {default:{'$':3,'%':0.5,use:'%',extra:true}},
 {default:{'$':'3','%':0.5,use:'%'}},
 {default:{'$':true,'%':0.5,use:'%'}},
 {default:{'$':3,'%':'0.5',use:'$'}},
 {default:{'$':-1,'%':0.5,use:'%'}},
 {default:{'$':3,'%':-0.5,use:'$'}},
 {default:{'$':Infinity,'%':0.5,use:'%'}},
 {default:{'$':3,'%':NaN,use:'$'}},
 {default:{'$':3,'%':0.5,use:'both'}},
 {default:DEFAULT_NEAR_STRIKE_RULE,AVGO:{'$':3,'%':-1,use:'$'}},
 {default:DEFAULT_NEAR_STRIKE_RULE,AVGO:DEFAULT_NEAR_STRIKE_RULE,avgo:DEFAULT_NEAR_STRIKE_RULE},
 {default:DEFAULT_NEAR_STRIKE_RULE,'':DEFAULT_NEAR_STRIKE_RULE},
 {default:DEFAULT_NEAR_STRIKE_RULE,' AVGO':DEFAULT_NEAR_STRIKE_RULE},
 {default:DEFAULT_NEAR_STRIKE_RULE,'A_VGO':DEFAULT_NEAR_STRIKE_RULE},
 {default:DEFAULT_NEAR_STRIKE_RULE,DEFAULT:DEFAULT_NEAR_STRIKE_RULE}
];
for(const invalid of invalidRules)assert.throws(()=>parseNearStrikeRules(invalid));
console.log('PASS: symbol overrides, case normalization, configured/built-in defaults, strict whole-config validation including inactive values');
const {groupShortITM}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const groups=groupShortITM([
 {side:'Short',label:'ITM',days:15},{side:'Long',label:'ITM',days:0},
 {side:'Short',label:'OTM',days:1},{side:'Short',label:'ITM',days:7},
 {side:'Short',label:'ITM',days:0},{side:'Short',label:'ITM',days:0},
 {side:'Short',label:'Unknown',days:2},{side:'Short',label:'ITM',days:null},
 {side:'Short',label:'ITM',days:-1},{side:'Short',label:'ATM',days:3}
]);
assert.deepEqual(groups.map(g=>g.dte),[0,7,15]);
assert.equal(groups[0].rows.length,2);
assert.deepEqual(groupShortITM([]),[]);
console.log('PASS: short ITM only, numeric DTE ordering including 15, empty groups hidden, expired/unknown excluded');
const {strikeDistance,compareDistance}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
assert.equal(strikeDistance(100,110).dollars,-10);
assert.equal(strikeDistance(100,110).percent.toFixed(2),'-9.09');
assert.equal(strikeDistance(100,90).dollars,10);
assert.equal(strikeDistance(100,90).percent.toFixed(2),'11.11');
assert.equal(strikeDistance(123.45,100).percent.toFixed(2),'23.45','Synthetic stock-price rise needed to reach the strike');
for(const type of ['CALL','PUT']){
 for(const last of [80,100,130]){
  assert.equal(relation({...p,type},{last}).distance,strikeDistance(100,last).percent,'Display and sorting use the same signed stock-price percentage');
 }
}
assert.deepEqual(strikeDistance(100,100),{dollars:0,percent:0});
assert.equal(strikeDistance(100,null).percent,null);
assert.equal(strikeDistance(0,10).percent,null);
for(const price of [0,-1,NaN,Infinity,undefined])assert.equal(strikeDistance(100,price).percent,null);
assert.deepEqual([null,10,-10,0,null,-2].sort(compareDistance),[-10,-2,0,10,null,null]);
console.log('PASS: stock-price-based distance percentage, synthetic example, matching display/sort values, signed direction, invalid prices and missing values');
const {compareMoneyness}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
const ranked=[
 {id:'far-otm-put',...relation({...p,type:'PUT'},{last:120})},
 {id:'near-itm-put',...relation({...p,type:'PUT'},{last:99})},
 {id:'deep-itm-call',...relation(p,{last:130})},
 {id:'near-otm-call',...relation(p,{last:99.5})},
 {id:'deep-itm-put',...relation({...p,type:'PUT'},{last:80})},
 {id:'atm',...relation(p,{last:100})},
 {id:'unknown',...relation(p)},
 {id:'otm-call',...relation(p,{last:90})}
].map(row=>({...row,side:'Short',days:7})).sort(compareMoneyness);
assert.deepEqual(ranked.map(p=>p.id),['near-itm-put','deep-itm-call','deep-itm-put','atm','near-otm-call','otm-call','far-otm-put','unknown']);
const expiryRanked=[
 {id:'itm-later-deep',days:30,...relation(p,{last:150})},
 {id:'otm-soon-near',days:0,...relation(p,{last:99})},
 {id:'itm-soon-near',days:5,...relation(p,{last:102})},
 {id:'otm-later-deep',days:30,...relation({...p,type:'PUT'},{last:160})},
 {id:'itm-missing-expiry',days:null,...relation(p,{last:180})},
 {id:'itm-soon-deep',days:5,...relation({...p,type:'PUT'},{last:80})},
 {id:'otm-soon-deep',days:0,...relation(p,{last:90})},
 {id:'unknown-price',days:0,...relation(p)},
 {id:'otm-missing-expiry',days:null,...relation(p,{last:50})}
].map(row=>({...row,side:'Short'})).sort(compareMoneyness);
const expiryOrder=[
 'itm-soon-near','itm-soon-deep','itm-later-deep','itm-missing-expiry',
 'otm-soon-near','otm-soon-deep','otm-later-deep','otm-missing-expiry','unknown-price'
];
assert.deepEqual(expiryRanked.map(p=>p.id),expiryOrder);
console.log('PASS: ITM before OTM, expiry days ascending, absolute distance ascending within each expiry, missing expiry last within its group, unknown prices last');
const sideRanked=expiryRanked.flatMap(row=>[
 {...row,side:'Long'},{...row,side:'Short'}
]).reverse().sort(compareMoneyness);
assert.deepEqual(sideRanked.map(row=>`${row.side}:${row.id}`),
 ['Short','Long'].flatMap(side=>expiryOrder.map(id=>`${side}:${id}`)));
console.log('PASS: all Shorts including OTM and unknown prices precede all Longs; moneyness, expiry and depth ordering preserved within both sides');
const {isExpiredForView}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
assert.equal(isExpiredForView('2026-09-24',new Date('2026-09-24T19:59:59Z')),false);
assert.equal(isExpiredForView('2026-09-24',new Date('2026-09-24T20:00:00Z')),true);
assert.equal(isExpiredForView('2026-09-25',new Date('2026-09-24T23:00:00Z')),false);
assert.equal(isExpiredForView('2026-09-23',new Date('2026-09-24T12:00:00Z')),true);
assert.equal(isExpiredForView('2026-12-18',new Date('2026-12-18T20:59:59Z')),false);
assert.equal(isExpiredForView('2026-12-18',new Date('2026-12-18T21:00:00Z')),true);
assert.equal(isExpiredForView(null,new Date()),false);
console.log('PASS: 4 PM Eastern display cutoff, summer/winter offsets, past/future dates, unknown expiry');
