import{B as J,d as Q,R as X,z as Z,f as j,Y as $,D as ee,v as E,x as z,S as te,A as x,C as w,E as _,m as c,F as ne,G as ie,o as a,c as l,a as s,H as se,h as L,J as D,i as R,j as v,t as b,r as S,w as C,e as h,T as oe,g as K,K as I,L as M,M as ae,u as re,k as p,n as H,N as T,p as N,q as le,y as ue}from"./index-DQFLtC17.js";import{O as de,C as ce}from"./index-CbuUbQ5q.js";import{c as A,_ as me}from"./_plugin-vue_export-helper-Dmv76B0U.js";import{M as pe}from"./message-square-text-BVpWs8OO.js";import{M as fe}from"./megaphone-DxFiFi0J.js";import{B as he}from"./bot-OozTMyQl.js";import{A as be}from"./activity-DxhQ9Ksv.js";import{G as ve}from"./git-branch-Daru-_m6.js";import{P as ye,S as ge}from"./settings-B4assXN2.js";import{S as ke}from"./shield-check-D6DVk5aA.js";import{S as Ie}from"./sparkles-Dv646qVE.js";import{S as Le}from"./search-_eIfnFLG.js";/**
 * @license lucide-vue-next v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const Oe=A("BellIcon",[["path",{d:"M10.268 21a2 2 0 0 0 3.464 0",key:"vwvbt9"}],["path",{d:"M3.262 15.326A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673C19.41 13.956 18 12.499 18 8A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.738 7.326",key:"11g9vi"}]]);/**
 * @license lucide-vue-next v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const U=A("ChevronDownIcon",[["path",{d:"m6 9 6 6 6-6",key:"qrunsl"}]]);/**
 * @license lucide-vue-next v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const Ce=A("LayoutDashboardIcon",[["rect",{width:"7",height:"9",x:"3",y:"3",rx:"1",key:"10lvy0"}],["rect",{width:"7",height:"5",x:"14",y:"3",rx:"1",key:"16une8"}],["rect",{width:"7",height:"9",x:"14",y:"12",rx:"1",key:"1hutg5"}],["rect",{width:"7",height:"5",x:"3",y:"16",rx:"1",key:"ldoo1y"}]]);/**
 * @license lucide-vue-next v0.468.0 - ISC
 *
 * This source code is licensed under the ISC license.
 * See the LICENSE file in the root directory of this source tree.
 */const xe=A("MenuIcon",[["line",{x1:"4",x2:"20",y1:"12",y2:"12",key:"1e0a9i"}],["line",{x1:"4",x2:"20",y1:"6",y2:"6",key:"1owob3"}],["line",{x1:"4",x2:"20",y1:"18",y2:"18",key:"yk5zj1"}]]);var we=`
    .p-menu {
        background: dt('menu.background');
        color: dt('menu.color');
        border: 1px solid dt('menu.border.color');
        border-radius: dt('menu.border.radius');
        min-width: 12.5rem;
    }

    .p-menu-list {
        margin: 0;
        padding: dt('menu.list.padding');
        outline: 0 none;
        list-style: none;
        display: flex;
        flex-direction: column;
        gap: dt('menu.list.gap');
    }

    .p-menu-item-content {
        transition:
            background dt('menu.transition.duration'),
            color dt('menu.transition.duration');
        border-radius: dt('menu.item.border.radius');
        color: dt('menu.item.color');
        overflow: hidden;
    }

    .p-menu-item-link {
        cursor: pointer;
        display: flex;
        align-items: center;
        text-decoration: none;
        overflow: hidden;
        position: relative;
        color: inherit;
        padding: dt('menu.item.padding');
        gap: dt('menu.item.gap');
        user-select: none;
        outline: 0 none;
    }

    .p-menu-item-label {
        line-height: 1;
    }

    .p-menu-item-icon {
        color: dt('menu.item.icon.color');
    }

    .p-menu-item.p-focus .p-menu-item-content {
        color: dt('menu.item.focus.color');
        background: dt('menu.item.focus.background');
    }

    .p-menu-item.p-focus .p-menu-item-icon {
        color: dt('menu.item.icon.focus.color');
    }

    .p-menu-item:not(.p-disabled) .p-menu-item-content:hover {
        color: dt('menu.item.focus.color');
        background: dt('menu.item.focus.background');
    }

    .p-menu-item:not(.p-disabled) .p-menu-item-content:hover .p-menu-item-icon {
        color: dt('menu.item.icon.focus.color');
    }

    .p-menu-overlay {
        box-shadow: dt('menu.shadow');
    }

    .p-menu-submenu-label {
        background: dt('menu.submenu.label.background');
        padding: dt('menu.submenu.label.padding');
        color: dt('menu.submenu.label.color');
        font-weight: dt('menu.submenu.label.font.weight');
    }

    .p-menu-separator {
        border-block-start: 1px solid dt('menu.separator.border.color');
    }
`,Se={root:function(e){var n=e.props;return["p-menu p-component",{"p-menu-overlay":n.popup}]},start:"p-menu-start",list:"p-menu-list",submenuLabel:"p-menu-submenu-label",separator:"p-menu-separator",end:"p-menu-end",item:function(e){var n=e.instance;return["p-menu-item",{"p-focus":n.id===n.focusedOptionId,"p-disabled":n.disabled()}]},itemContent:"p-menu-item-content",itemLink:"p-menu-item-link",itemIcon:"p-menu-item-icon",itemLabel:"p-menu-item-label"},Me=J.extend({name:"menu",style:we,classes:Se}),Ae={name:"BaseMenu",extends:Z,props:{popup:{type:Boolean,default:!1},model:{type:Array,default:null},appendTo:{type:[String,Object],default:"body"},autoZIndex:{type:Boolean,default:!0},baseZIndex:{type:Number,default:0},tabindex:{type:Number,default:0},ariaLabel:{type:String,default:null},ariaLabelledby:{type:String,default:null}},style:Me,provide:function(){return{$pcMenu:this,$parentInstance:this}}},q={name:"Menuitem",hostName:"Menu",extends:Z,inheritAttrs:!1,emits:["item-click","item-mousemove"],props:{item:null,templates:null,id:null,focusedOptionId:null,index:null},methods:{getItemProp:function(e,n){return e&&e.item?ne(e.item[n]):void 0},getPTOptions:function(e){return this.ptm(e,{context:{item:this.item,index:this.index,focused:this.isItemFocused(),disabled:this.disabled()}})},isItemFocused:function(){return this.focusedOptionId===this.id},onItemClick:function(e){var n=this.getItemProp(this.item,"command");n&&n({originalEvent:e,item:this.item.item}),this.$emit("item-click",{originalEvent:e,item:this.item,id:this.id})},onItemMouseMove:function(e){this.$emit("item-mousemove",{originalEvent:e,item:this.item,id:this.id})},visible:function(){return typeof this.item.visible=="function"?this.item.visible():this.item.visible!==!1},disabled:function(){return typeof this.item.disabled=="function"?this.item.disabled():this.item.disabled},label:function(){return typeof this.item.label=="function"?this.item.label():this.item.label},getMenuItemProps:function(e){return{action:c({class:this.cx("itemLink"),tabindex:"-1"},this.getPTOptions("itemLink")),icon:c({class:[this.cx("itemIcon"),e.icon]},this.getPTOptions("itemIcon")),label:c({class:this.cx("itemLabel")},this.getPTOptions("itemLabel"))}}},computed:{dataP:function(){return j({focus:this.isItemFocused(),disabled:this.disabled()})}},directives:{ripple:X}},Pe=["id","aria-label","aria-disabled","data-p-focused","data-p-disabled","data-p"],Ee=["data-p"],ze=["href","target"],Ke=["data-p"],Te=["data-p"];function De(t,e,n,r,m,i){var O=ie("ripple");return i.visible()?(a(),l("li",c({key:0,id:n.id,class:[t.cx("item"),n.item.class],role:"menuitem",style:n.item.style,"aria-label":i.label(),"aria-disabled":i.disabled(),"data-p-focused":i.isItemFocused(),"data-p-disabled":i.disabled()||!1,"data-p":i.dataP},i.getPTOptions("item")),[s("div",c({class:t.cx("itemContent"),onClick:e[0]||(e[0]=function(y){return i.onItemClick(y)}),onMousemove:e[1]||(e[1]=function(y){return i.onItemMouseMove(y)}),"data-p":i.dataP},i.getPTOptions("itemContent")),[n.templates.item?n.templates.item?(a(),L(R(n.templates.item),{key:1,item:n.item,label:i.label(),props:i.getMenuItemProps(n.item)},null,8,["item","label","props"])):v("",!0):se((a(),l("a",c({key:0,href:n.item.url,class:t.cx("itemLink"),target:n.item.target,tabindex:"-1"},i.getPTOptions("itemLink")),[n.templates.itemicon?(a(),L(R(n.templates.itemicon),{key:0,item:n.item,class:D(t.cx("itemIcon"))},null,8,["item","class"])):n.item.icon?(a(),l("span",c({key:1,class:[t.cx("itemIcon"),n.item.icon],"data-p":i.dataP},i.getPTOptions("itemIcon")),null,16,Ke)):v("",!0),s("span",c({class:t.cx("itemLabel"),"data-p":i.dataP},i.getPTOptions("itemLabel")),b(i.label()),17,Te)],16,ze)),[[O]])],16,Ee)],16,Pe)):v("",!0)}q.render=De;function W(t){return Ve(t)||Fe(t)||Be(t)||Re()}function Re(){throw new TypeError(`Invalid attempt to spread non-iterable instance.
In order to be iterable, non-array objects must have a [Symbol.iterator]() method.`)}function Be(t,e){if(t){if(typeof t=="string")return B(t,e);var n={}.toString.call(t).slice(8,-1);return n==="Object"&&t.constructor&&(n=t.constructor.name),n==="Map"||n==="Set"?Array.from(t):n==="Arguments"||/^(?:Ui|I)nt(?:8|16|32)(?:Clamped)?Array$/.test(n)?B(t,e):void 0}}function Fe(t){if(typeof Symbol!="undefined"&&t[Symbol.iterator]!=null||t["@@iterator"]!=null)return Array.from(t)}function Ve(t){if(Array.isArray(t))return B(t)}function B(t,e){(e==null||e>t.length)&&(e=t.length);for(var n=0,r=Array(e);n<e;n++)r[n]=t[n];return r}var G={name:"Menu",extends:Ae,inheritAttrs:!1,emits:["show","hide","focus","blur"],data:function(){return{overlayVisible:!1,focused:!1,focusedOptionIndex:-1,selectedOptionIndex:-1}},target:null,outsideClickListener:null,scrollHandler:null,resizeListener:null,container:null,list:null,mounted:function(){this.popup||(this.bindResizeListener(),this.bindOutsideClickListener())},beforeUnmount:function(){this.unbindResizeListener(),this.unbindOutsideClickListener(),this.scrollHandler&&(this.scrollHandler.destroy(),this.scrollHandler=null),this.target=null,this.container&&this.autoZIndex&&z.clear(this.container),this.container=null},methods:{itemClick:function(e){var n=e.item;this.disabled(n)||(n.command&&n.command(e),this.overlayVisible&&this.hide(),!this.popup&&this.focusedOptionIndex!==e.id&&(this.focusedOptionIndex=e.id))},itemMouseMove:function(e){this.focused&&(this.focusedOptionIndex=e.id)},onListFocus:function(e){this.focused=!0,!this.popup&&this.changeFocusedOptionIndex(0),this.$emit("focus",e)},onListBlur:function(e){this.focused=!1,this.focusedOptionIndex=-1,this.$emit("blur",e)},onListKeyDown:function(e){switch(e.code){case"ArrowDown":this.onArrowDownKey(e);break;case"ArrowUp":this.onArrowUpKey(e);break;case"Home":this.onHomeKey(e);break;case"End":this.onEndKey(e);break;case"Enter":case"NumpadEnter":this.onEnterKey(e);break;case"Space":this.onSpaceKey(e);break;case"Escape":this.popup&&(x(this.target),this.hide());case"Tab":this.overlayVisible&&this.hide();break}},onArrowDownKey:function(e){var n=this.findNextOptionIndex(this.focusedOptionIndex);this.changeFocusedOptionIndex(n),e.preventDefault()},onArrowUpKey:function(e){if(e.altKey&&this.popup)x(this.target),this.hide(),e.preventDefault();else{var n=this.findPrevOptionIndex(this.focusedOptionIndex);this.changeFocusedOptionIndex(n),e.preventDefault()}},onHomeKey:function(e){this.changeFocusedOptionIndex(0),e.preventDefault()},onEndKey:function(e){this.changeFocusedOptionIndex(w(this.container,'li[data-pc-section="item"][data-p-disabled="false"]').length-1),e.preventDefault()},onEnterKey:function(e){var n=_(this.list,'li[id="'.concat("".concat(this.focusedOptionIndex),'"]')),r=n&&_(n,'a[data-pc-section="itemlink"]');this.popup&&x(this.target),r?r.click():n&&n.click(),e.preventDefault()},onSpaceKey:function(e){this.onEnterKey(e)},findNextOptionIndex:function(e){var n=w(this.container,'li[data-pc-section="item"][data-p-disabled="false"]'),r=W(n).findIndex(function(m){return m.id===e});return r>-1?r+1:0},findPrevOptionIndex:function(e){var n=w(this.container,'li[data-pc-section="item"][data-p-disabled="false"]'),r=W(n).findIndex(function(m){return m.id===e});return r>-1?r-1:0},changeFocusedOptionIndex:function(e){var n=w(this.container,'li[data-pc-section="item"][data-p-disabled="false"]'),r=e>=n.length?n.length-1:e<0?0:e;r>-1&&(this.focusedOptionIndex=n[r].getAttribute("id"))},toggle:function(e,n){this.overlayVisible?this.hide():this.show(e,n)},show:function(e,n){this.overlayVisible=!0,this.target=n!=null?n:e.currentTarget},hide:function(){this.overlayVisible=!1,this.target=null},onEnter:function(e){te(e,{position:"absolute",top:"0"}),this.alignOverlay(),this.bindOutsideClickListener(),this.bindResizeListener(),this.bindScrollListener(),this.autoZIndex&&z.set("menu",e,this.baseZIndex||this.$primevue.config.zIndex.menu),this.popup&&x(this.list),this.$emit("show")},onLeave:function(){this.unbindOutsideClickListener(),this.unbindResizeListener(),this.unbindScrollListener(),this.$emit("hide")},onAfterLeave:function(e){this.autoZIndex&&z.clear(e)},alignOverlay:function(){ee(this.container,this.target);var e=E(this.target);e>E(this.container)&&(this.container.style.minWidth=E(this.target)+"px")},bindOutsideClickListener:function(){var e=this;this.outsideClickListener||(this.outsideClickListener=function(n){var r=e.container&&!e.container.contains(n.target),m=!(e.target&&(e.target===n.target||e.target.contains(n.target)));e.overlayVisible&&r&&m?e.hide():!e.popup&&r&&m&&(e.focusedOptionIndex=-1)},document.addEventListener("click",this.outsideClickListener,!0))},unbindOutsideClickListener:function(){this.outsideClickListener&&(document.removeEventListener("click",this.outsideClickListener,!0),this.outsideClickListener=null)},bindScrollListener:function(){var e=this;this.scrollHandler||(this.scrollHandler=new ce(this.target,function(){e.overlayVisible&&e.hide()})),this.scrollHandler.bindScrollListener()},unbindScrollListener:function(){this.scrollHandler&&this.scrollHandler.unbindScrollListener()},bindResizeListener:function(){var e=this;this.resizeListener||(this.resizeListener=function(){e.overlayVisible&&!$()&&e.hide()},window.addEventListener("resize",this.resizeListener))},unbindResizeListener:function(){this.resizeListener&&(window.removeEventListener("resize",this.resizeListener),this.resizeListener=null)},visible:function(e){return typeof e.visible=="function"?e.visible():e.visible!==!1},disabled:function(e){return typeof e.disabled=="function"?e.disabled():e.disabled},label:function(e){return typeof e.label=="function"?e.label():e.label},onOverlayClick:function(e){de.emit("overlay-click",{originalEvent:e,target:this.target})},containerRef:function(e){this.container=e},listRef:function(e){this.list=e}},computed:{focusedOptionId:function(){return this.focusedOptionIndex!==-1?this.focusedOptionIndex:null},dataP:function(){return j({popup:this.popup})}},components:{PVMenuitem:q,Portal:Q}},_e=["id","data-p"],He=["id","tabindex","aria-activedescendant","aria-label","aria-labelledby"],Ne=["id"];function Ue(t,e,n,r,m,i){var O=S("PVMenuitem"),y=S("Portal");return a(),L(y,{appendTo:t.appendTo,disabled:!t.popup},{default:C(function(){return[h(oe,c({name:"p-anchored-overlay",onEnter:i.onEnter,onLeave:i.onLeave,onAfterLeave:i.onAfterLeave},t.ptm("transition")),{default:C(function(){return[!t.popup||m.overlayVisible?(a(),l("div",c({key:0,ref:i.containerRef,id:t.$id,class:t.cx("root"),onClick:e[3]||(e[3]=function(){return i.onOverlayClick&&i.onOverlayClick.apply(i,arguments)}),"data-p":i.dataP},t.ptmi("root")),[t.$slots.start?(a(),l("div",c({key:0,class:t.cx("start")},t.ptm("start")),[K(t.$slots,"start")],16)):v("",!0),s("ul",c({ref:i.listRef,id:t.$id+"_list",class:t.cx("list"),role:"menu",tabindex:t.tabindex,"aria-activedescendant":m.focused?i.focusedOptionId:void 0,"aria-label":t.ariaLabel,"aria-labelledby":t.ariaLabelledby,onFocus:e[0]||(e[0]=function(){return i.onListFocus&&i.onListFocus.apply(i,arguments)}),onBlur:e[1]||(e[1]=function(){return i.onListBlur&&i.onListBlur.apply(i,arguments)}),onKeydown:e[2]||(e[2]=function(){return i.onListKeyDown&&i.onListKeyDown.apply(i,arguments)})},t.ptm("list")),[(a(!0),l(I,null,M(t.model,function(u,f){return a(),l(I,{key:i.label(u)+f.toString()},[u.items&&i.visible(u)&&!u.separator?(a(),l(I,{key:0},[u.items?(a(),l("li",c({key:0,id:t.$id+"_"+f,class:[t.cx("submenuLabel"),u.class],role:"none"},{ref_for:!0},t.ptm("submenuLabel")),[K(t.$slots,t.$slots.submenulabel?"submenulabel":"submenuheader",{item:u},function(){return[ae(b(i.label(u)),1)]})],16,Ne)):v("",!0),(a(!0),l(I,null,M(u.items,function(d,o){return a(),l(I,{key:d.label+f+"_"+o},[i.visible(d)&&!d.separator?(a(),L(O,{key:0,id:t.$id+"_"+f+"_"+o,item:d,templates:t.$slots,focusedOptionId:i.focusedOptionId,unstyled:t.unstyled,onItemClick:i.itemClick,onItemMousemove:i.itemMouseMove,pt:t.pt},null,8,["id","item","templates","focusedOptionId","unstyled","onItemClick","onItemMousemove","pt"])):i.visible(d)&&d.separator?(a(),l("li",c({key:"separator"+f+o,class:[t.cx("separator"),u.class],style:d.style,role:"separator"},{ref_for:!0},t.ptm("separator")),null,16)):v("",!0)],64)}),128))],64)):i.visible(u)&&u.separator?(a(),l("li",c({key:"separator"+f.toString(),class:[t.cx("separator"),u.class],style:u.style,role:"separator"},{ref_for:!0},t.ptm("separator")),null,16)):(a(),L(O,{key:i.label(u)+f.toString(),id:t.$id+"_"+f,item:u,index:f,templates:t.$slots,focusedOptionId:i.focusedOptionId,unstyled:t.unstyled,onItemClick:i.itemClick,onItemMousemove:i.itemMouseMove,pt:t.pt},null,8,["id","item","index","templates","focusedOptionId","unstyled","onItemClick","onItemMousemove","pt"]))],64)}),128))],16,He),t.$slots.end?(a(),l("div",c({key:1,class:t.cx("end")},t.ptm("end")),[K(t.$slots,"end")],16)):v("",!0)],16,_e)):v("",!0)]}),_:3},16,["onEnter","onLeave","onAfterLeave"])]}),_:3},8,["appendTo","disabled"])}G.render=Ue;const We=[{label:"Workspace",items:[{label:"Overview",route:"dashboard",icon:Ce}]},{label:"Engage",items:[{label:"Available Templates",route:"templates",icon:pe,readOnly:!0},{label:"Bulk Messaging",route:"campaigns",icon:fe},{label:"AI Queue",route:"ai-queue",icon:he},{label:"Polls & Forms",route:"polls",icon:be}]},{label:"Automate",items:[{label:"Flow Builder",route:"flows",icon:ve},{label:"Connectors",route:"connectors",icon:ye}]},{label:"Administration",items:[{label:"Audit & Health",route:"health",icon:ke},{label:"Company Settings",route:"settings",icon:ge}]}],Ze={class:"app-shell"},je={class:"brand"},qe={class:"brand-mark"},Ge={class:"tenant-card"},Ye={class:"nav-label"},Je={key:0},Qe={class:"sidebar-footer"},Xe={class:"main-shell"},$e={class:"topbar"},et={class:"global-search"},tt={class:"top-actions"},nt={class:"content"},it={__name:"AppShell",setup(t){const e=re(),n=le(),r=ue(),m=N(),i=N(!1),O=T(()=>{var d;return((d=e.boot)==null?void 0:d.site)||"Current Frappe site"}),y=T(()=>{var d,o;return((o=(d=e.user)==null?void 0:d.roles)==null?void 0:o.find(P=>P.startsWith("WhatsApp Core")))||"Site user"}),u=T(()=>{var d;return(((d=e.user)==null?void 0:d.full_name)||"U").split(" ").slice(0,2).map(o=>o[0]).join("").toUpperCase()}),f=[{label:"My profile",icon:"pi pi-user"},{label:"Theme",icon:"pi pi-moon"},{separator:!0},{label:"Sign out",icon:"pi pi-sign-out",command:async()=>{await e.logout(),r.push({name:"login"})}}];return(d,o)=>{var F,V;const P=S("RouterLink"),Y=S("RouterView");return a(),l("div",Ze,[s("aside",{class:D(["sidebar",{open:i.value}])},[s("div",je,[s("div",qe,[h(p(Ie),{size:19})]),o[3]||(o[3]=s("div",null,[s("strong",null,"WhatsApp Core"),s("span",null,"Company workspace")],-1))]),s("div",Ge,[o[5]||(o[5]=s("div",{class:"tenant-avatar"},"WA",-1)),s("div",null,[o[4]||(o[4]=s("span",null,"Current site",-1)),s("strong",null,b(O.value),1)]),h(p(U),{size:15})]),s("nav",null,[(a(!0),l(I,null,M(p(We),g=>(a(),l("section",{key:g.label,class:"nav-group"},[s("div",Ye,b(g.label),1),(a(!0),l(I,null,M(g.items,k=>(a(),L(P,{key:`${g.label}-${k.label}`,to:{name:k.route},class:D(["nav-item",{active:p(n).name===k.route}]),onClick:o[0]||(o[0]=st=>i.value=!1)},{default:C(()=>[(a(),L(R(k.icon),{size:18})),s("span",null,b(k.label),1),k.badge?(a(),l("em",Je,b(k.badge),1)):v("",!0)]),_:2},1032,["to","class"]))),128))]))),128))]),s("div",Qe,[o[6]||(o[6]=s("div",null,[s("span",{class:"status-dot"}),s("strong",null,"Core UI connected")],-1)),s("small",null,b((F=p(e).boot)==null?void 0:F.site),1)])],2),s("div",Xe,[s("header",$e,[h(p(H),{class:"mobile-menu",text:"",rounded:"",onClick:o[1]||(o[1]=g=>i.value=!i.value)},{default:C(()=>[h(p(xe),{size:21})]),_:1}),s("div",et,[h(p(Le),{size:18}),o[7]||(o[7]=s("input",{placeholder:"Search flows, campaigns and templates..."},null,-1)),o[8]||(o[8]=s("kbd",null,"⌘ K",-1))]),s("div",tt,[h(p(H),{text:"",rounded:"",severity:"secondary"},{default:C(()=>[h(p(Oe),{size:19})]),_:1}),s("button",{class:"profile",onClick:o[2]||(o[2]=g=>m.value.toggle(g))},[s("span",null,b(u.value),1),s("div",null,[s("strong",null,b((V=p(e).user)==null?void 0:V.full_name),1),s("small",null,b(y.value),1)]),h(p(U),{size:15})]),h(p(G),{ref_key:"profileMenu",ref:m,model:f,popup:""},null,512)])]),s("main",nt,[h(Y)])])])}}},vt=me(it,[["__scopeId","data-v-97fc0c9d"]]);export{vt as default};
