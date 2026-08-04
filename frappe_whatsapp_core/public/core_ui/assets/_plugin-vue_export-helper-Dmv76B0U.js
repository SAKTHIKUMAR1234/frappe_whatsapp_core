import{aP as n}from"./index-DQFLtC17.js";/**
 * @license lucide-vue-next v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const d=t=>t.replace(/([a-z0-9])([A-Z])/g,"$1-$2").toLowerCase();/**
 * @license lucide-vue-next v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */var s={xmlns:"http://www.w3.org/2000/svg",width:24,height:24,viewBox:"0 0 24 24",fill:"none",stroke:"currentColor","stroke-width":2,"stroke-linecap":"round","stroke-linejoin":"round"};/**
 * @license lucide-vue-next v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const h=({size:t,strokeWidth:e=2,absoluteStrokeWidth:o,color:r,iconNode:c,name:a,class:w,...l},{slots:i})=>n("svg",{...s,width:t||s.width,height:t||s.height,stroke:r||s.stroke,"stroke-width":o?Number(e)*24/Number(t):e,class:["lucide",`lucide-${d(a!=null?a:"icon")}`],...l},[...c.map(u=>n(...u)),...i.default?[i.default()]:[]]);/**
 * @license lucide-vue-next v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const p=(t,e)=>(o,{slots:r})=>n(h,{...o,iconNode:e,name:t},r),f=(t,e)=>{const o=t.__vccOpts||t;for(const[r,c]of e)o[r]=c;return o};export{f as _,p as c};
