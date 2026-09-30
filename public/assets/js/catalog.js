const treeElement=document.querySelector("#category-tree"),shopGrid=document.querySelector("#shop-grid"),template=document.querySelector("#shop-card-template"),resultTitle=document.querySelector("#result-title"),resultCount=document.querySelector("#result-count"),emptyState=document.querySelector("#empty-state"),searchForm=document.querySelector("#search-form"),searchInput=document.querySelector("#search-input"),categoryDropdown=document.querySelector("#categories"),categoryMenu=document.querySelector("#category-menu-trigger"),categoryMenuLabel=document.querySelector("#category-menu-label"),categoryPopover=document.querySelector("#category-popover");
let categoryTree=[],shops=[],selectedCategory=null,selectedLabel="",query="";
const expanded=new Set();
let reelStops=[];
const faNumber=value=>new Intl.NumberFormat("fa-IR").format(value);
const finePointer=matchMedia("(hover: hover) and (pointer: fine)");
const loaderIcon='<svg viewBox="0 0 16 16" shape-rendering="crispEdges"><path d="M5 1h2v2h2V2h2v3h2v5h-2v3H9v2H5v-2H3v-2H1V6h2V3h2zM6 4h4v2H8v5H6zM3 7h3v2H3z"/></svg>';
const loaderMarkup=label=>`<div class="kahoo-loader catalog-loader" role="status"><div class="kahoo-loader-icons" aria-hidden="true">${loaderIcon.repeat(3)}</div><span>${label}</span></div>`;
const sessionId=localStorage.getItem("kahoo_session")||crypto.randomUUID();localStorage.setItem("kahoo_session",sessionId);

async function api(path,options={}){const headers=new Headers(options.headers||{});headers.set("X-Kahoo-Session",sessionId);const response=await fetch(path,{...options,headers});if(!response.ok)throw new Error(`API ${response.status}`);return response.json()}
function track(event_type,details={}){api("/api/analytics/event",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({event_type,...details})}).catch(()=>{})}

function collapseBranch(node){expanded.delete(node.code);node.children.forEach(collapseBranch)}
let branchOpenTimer;
function revealBranch(node,siblings){
  if(!node.children.length||expanded.has(node.code))return;
  siblings.filter(sibling=>sibling!==node).forEach(collapseBranch);expanded.add(node.code);renderTree();
}
function queueBranch(node,siblings){clearTimeout(branchOpenTimer);if(node.children.length&&!expanded.has(node.code))branchOpenTimer=setTimeout(()=>revealBranch(node,siblings),260)}
function treeNode(node,siblings){
  const item=document.createElement("li");item.className=`tree-item level-${node.level}`;item.setAttribute("role","treeitem");item.setAttribute("aria-selected",node.code===selectedCategory);
  const row=document.createElement("div");row.className=`tree-node${node.code===selectedCategory?" selected":""}${expanded.has(node.code)?" active":""}`;
  const toggle=document.createElement("span");toggle.className=`tree-toggle${node.children.length?"":" empty"}${expanded.has(node.code)?" expanded":""}`;toggle.setAttribute("aria-hidden","true");
  const select=document.createElement("button");select.className="tree-select";select.type="button";select.innerHTML=`<span>${node.label_fa}</span><small>${faNumber(node.count)}</small>`;select.title=`GS1 ${node.code}`;select.addEventListener("click",event=>{if(!finePointer.matches&&node.children.length&&!expanded.has(node.code)){event.preventDefault();revealBranch(node,siblings);return}selectedCategory=node.code;selectedLabel=node.label_fa;renderTree();closeCategoryMenu();loadShops()});
  row.addEventListener("pointerenter",event=>{if(event.pointerType==="mouse")queueBranch(node,siblings)});
  row.append(select,toggle);item.append(row);
  return item;
}

function renderTree(){
  treeElement.innerHTML="";let siblings=categoryTree,depth=0;
  while(siblings.length){
    const column=document.createElement("ul");column.className="tree-column";column.dataset.depth=depth;column.setAttribute("role","group");siblings.forEach(node=>column.append(treeNode(node,siblings)));treeElement.append(column);
    const branch=siblings.find(node=>expanded.has(node.code));if(!branch)break;siblings=branch.children;depth+=1;
  }
  categoryPopover.style.setProperty("--category-columns",treeElement.childElementCount);
  categoryMenuLabel.textContent=selectedCategory?selectedLabel:"دسته‌بندی‌ها";
}
function openCategoryMenu(){categoryPopover.hidden=false;categoryMenu.setAttribute("aria-expanded","true")}
function closeCategoryMenu(){clearTimeout(branchOpenTimer);categoryPopover.hidden=true;categoryMenu.setAttribute("aria-expanded","false")}
let categoryOpenTimer,categoryCloseTimer;
categoryDropdown.addEventListener("pointerenter",event=>{if(event.pointerType==="mouse"){clearTimeout(categoryCloseTimer);if(categoryPopover.hidden)categoryOpenTimer=setTimeout(openCategoryMenu,220)}});
categoryDropdown.addEventListener("pointerleave",event=>{if(event.pointerType==="mouse"){clearTimeout(categoryOpenTimer);categoryCloseTimer=setTimeout(closeCategoryMenu,260)}});
treeElement.addEventListener("pointerleave",()=>clearTimeout(branchOpenTimer));
categoryDropdown.addEventListener("focusin",()=>{clearTimeout(categoryOpenTimer);clearTimeout(categoryCloseTimer);openCategoryMenu()});
categoryDropdown.addEventListener("focusout",event=>{if(!categoryDropdown.contains(event.relatedTarget))closeCategoryMenu()});
categoryMenu.addEventListener("click",event=>{if(finePointer.matches&&event.detail>0)return;categoryPopover.hidden?openCategoryMenu():closeCategoryMenu()});
document.addEventListener("click",event=>{if(!event.target.closest("#categories"))closeCategoryMenu()});document.addEventListener("keydown",event=>{if(event.key==="Escape")closeCategoryMenu()});
function renderShops(){
  reelStops.forEach(stop=>stop());reelStops=[];shopGrid.innerHTML="";emptyState.hidden=shops.length>0;
  shops.forEach((shop,index)=>{
    const card=template.content.cloneNode(true),article=card.querySelector("article"),avatar=card.querySelector(".shop-avatar");article.style.animationDelay=`${index*35}ms`;article.tabIndex=0;article.setAttribute("role","button");article.setAttribute("aria-label",`نمایش اطلاعات ${shop.name}`);article.addEventListener("click",event=>{if(!event.target.closest("a,button"))openMerchantProfile(shop.id)});article.addEventListener("keydown",event=>{if(event.target===article&&(event.key==="Enter"||event.key===" ")){event.preventDefault();openMerchantProfile(shop.id)}});avatar.style.background=shop.avatar_color;const avatarImage=document.createElement("img");avatarImage.src=shop.avatar_url;avatarImage.alt=`تصویر پروفایل ${shop.name}`;avatarImage.loading="lazy";avatarImage.addEventListener("error",()=>{avatarImage.remove();avatar.textContent=shop.avatar_initial},{once:true});avatar.append(avatarImage);card.querySelector("h3").textContent=shop.name;card.querySelector(".shop-copy p").textContent=shop.handle;card.querySelector(".shop-description").textContent=shop.description;const visitLink=card.querySelector(".visit-link");visitLink.href=shop.instagram_url;visitLink.target="_blank";visitLink.addEventListener("click",()=>track("merchant_click",{merchant_id:shop.id,query,category_code:selectedCategory}));card.querySelector(".location").textContent=shop.city;
    const posts=card.querySelector(".post-grid"),track=document.createElement("div");posts.setAttribute("aria-label",`آخرین پست‌های ${shop.name}`);track.className="post-reel-track";posts.append(track);let reelIndex=0,reelTimer=null,resetTimer=null;
    const reelItems=shop.posts.length>3?[...shop.posts,...shop.posts.slice(0,3)]:shop.posts;
    reelItems.forEach((post,position)=>{const postIndex=position%shop.posts.length,cover=post.media?.[0]?.media_url||post.media_url,link=document.createElement("a"),img=document.createElement("img");link.className="post";link.href=post.permalink;link.target="_blank";link.rel="noreferrer";link.setAttribute("aria-label",`پست ${postIndex+1} از ${shop.name}${post.image_count>1?`، مجموعه ${post.image_count} تصویر`:""}`);img.src=cover;img.alt=`پست ${postIndex+1} فروشگاه ${shop.name}`;img.loading="lazy";link.append(img);if(post.image_count>1){const badge=document.createElement("span");badge.className="collection-count";badge.textContent=`▣ ${faNumber(post.image_count)}`;link.append(badge)}track.append(link)});
    const updateAccess=()=>{[...track.children].forEach((link,position)=>{const visible=position>=reelIndex&&position<reelIndex+3;link.tabIndex=visible?0:-1;link.setAttribute("aria-hidden",String(!visible))})},move=(animate=true)=>{track.style.transition=animate?"transform 900ms cubic-bezier(.4,0,.2,1)":"none";const step=(posts.clientWidth-10)/3+5;track.style.transform=`translate3d(${-reelIndex*step}px,0,0)`;updateAccess()},stopReel=()=>{if(reelTimer){clearInterval(reelTimer);reelTimer=null}},startReel=()=>{if(shop.posts.length>3&&!matchMedia("(prefers-reduced-motion: reduce)").matches&&!reelTimer&&!posts.matches(":hover")&&!posts.matches(":focus-within"))reelTimer=setInterval(()=>{reelIndex+=1;move();if(reelIndex===shop.posts.length){clearTimeout(resetTimer);resetTimer=setTimeout(()=>{reelIndex=0;move(false)},920)}},5600+index*350)};
    move(false);startReel();posts.addEventListener("mouseenter",stopReel);posts.addEventListener("mouseleave",startReel);posts.addEventListener("focusin",stopReel);posts.addEventListener("focusout",startReel);const observer=new ResizeObserver(()=>move(false));observer.observe(posts);reelStops.push(()=>{stopReel();clearTimeout(resetTimer);observer.disconnect()});shopGrid.append(card);
  });
  resultTitle.textContent=query?`نتایج «${searchInput.value.trim()}»`:selectedLabel;resultCount.textContent=`${faNumber(shops.length)} فروشگاه`;
}
const merchantDialog=document.querySelector("#merchant-dialog"),merchantDialogLoading=document.querySelector("#merchant-dialog-loading"),merchantDialogContent=document.querySelector("#merchant-dialog-content");
function storedItems(key){try{return JSON.parse(localStorage.getItem(key)||"[]")}catch{return []}}
function paintSave(button,saved,compact=false){button.classList.toggle("saved",saved);button.setAttribute("aria-pressed",String(saved));if(button.classList.contains("merchant-save")){const label=saved?"حذف فروشگاه از ذخیره‌ها":"ذخیره فروشگاه";button.setAttribute("aria-label",label);button.title=label;return}button.textContent=compact?(saved?"♥":"♡"):(saved?"ذخیره شده":"ذخیره")}
function toggleSaved(key,item,button,compact=false){const items=storedItems(key),index=items.findIndex(saved=>saved.key===item.key);if(index>=0)items.splice(index,1);else items.unshift(item);localStorage.setItem(key,JSON.stringify(items));paintSave(button,index<0,compact)}
function detailMetric(valueId,noteId,value,missing="از اینستاگرام دریافت نشده"){document.querySelector(valueId).textContent=value===null||value===undefined?"—":faNumber(value);document.querySelector(noteId).textContent=value===null||value===undefined?missing:"دریافت‌شده از اینستاگرام"}
async function openMerchantProfile(merchantId){
  merchantDialogLoading.innerHTML=loaderMarkup("در حال دریافت فروشگاه");merchantDialogLoading.hidden=false;merchantDialogContent.hidden=true;merchantDialog.showModal();
  try{
    const merchant=await api(`/api/merchants/${merchantId}`),avatar=document.querySelector("#detail-avatar");
    avatar.src=merchant.avatar_url;avatar.alt=`تصویر پروفایل ${merchant.name}`;avatar.style.background=merchant.avatar_color;
    const categoryLabels=(merchant.categories||[]).map(category=>category.label),categorySummary=categoryLabels.length?categoryLabels.slice(0,3).join("، ")+(categoryLabels.length>3?` +${faNumber(categoryLabels.length-3)} دسته`:""):merchant.category_label;
    document.querySelector("#detail-name").textContent=merchant.name;document.querySelector("#detail-handle").textContent=merchant.handle;document.querySelector("#detail-meta").textContent=`${categorySummary} · ${merchant.city}`;document.querySelector("#detail-bio").textContent=merchant.biography||"بیوی اینستاگرام در دسترس نیست";
    detailMetric("#detail-followers","#detail-followers-note",merchant.followers_count);detailMetric("#detail-following","#detail-following-note",merchant.following_count);detailMetric("#detail-former-names","#detail-former-note",merchant.former_username_count,"API اینستاگرام ارائه نمی‌کند");
    const created=document.querySelector("#detail-created"),createdNote=document.querySelector("#detail-created-note");created.textContent=merchant.account_created_at?new Intl.DateTimeFormat("fa-IR",{year:"numeric",month:"long"}).format(new Date(merchant.account_created_at)):"—";createdNote.textContent=merchant.account_created_at?"دریافت‌شده از اینستاگرام":"API اینستاگرام ارائه نمی‌کند";
    const instagram=document.querySelector("#detail-instagram");instagram.href=merchant.instagram_url;instagram.onclick=()=>track("merchant_click",{merchant_id:merchant.id});
    const merchantSave=document.querySelector("#detail-save"),merchantItem={key:String(merchant.id),id:merchant.id,name:merchant.name,handle:merchant.handle,description:merchant.biography||merchant.description,avatar_url:merchant.avatar_url,instagram_url:merchant.instagram_url,city:merchant.city};paintSave(merchantSave,storedItems("kahoo_saved_merchants").some(item=>item.key===merchantItem.key));merchantSave.onclick=()=>toggleSaved("kahoo_saved_merchants",merchantItem,merchantSave);
    document.querySelector("#detail-sync").textContent=merchant.metrics_updated_at?`به‌روزرسانی ${new Intl.DateTimeFormat("fa-IR",{dateStyle:"medium"}).format(new Date(merchant.metrics_updated_at))}`:"اطلاعات محدود";
    const posts=document.querySelector("#detail-posts");posts.innerHTML="";merchant.posts.forEach((post,index)=>{
      const media=post.media?.length?post.media:[{media_url:post.media_url}],tile=document.createElement("div"),link=document.createElement("a"),preview=document.createElement("span"),save=document.createElement("button"),item={key:post.key||post.permalink,merchant_id:merchant.id,merchant_name:merchant.name,permalink:post.permalink,media_url:media[0].media_url,image_count:media.length};
      tile.className="saved-post-tile";link.href=post.permalink;link.target="_blank";link.rel="noreferrer";link.setAttribute("aria-label",`پست ${index+1} از ${merchant.name}${media.length>1?`، مجموعه ${media.length} تصویر`:""}`);preview.className=`collection-preview count-${Math.min(media.length,4)}`;
      media.slice(0,4).forEach((item,mediaIndex)=>{const image=document.createElement("img");image.src=item.media_url;image.alt=`تصویر ${mediaIndex+1} از پست ${index+1} ${merchant.name}`;image.loading="lazy";preview.append(image)});link.append(preview);
      if(media.length>1){const badge=document.createElement("span");badge.className="collection-count";badge.textContent=`▣ ${faNumber(media.length)}`;link.append(badge)}
      save.type="button";save.className="post-save";save.setAttribute("aria-label","ذخیره پست");paintSave(save,storedItems("kahoo_saved_posts").some(saved=>saved.key===item.key),true);save.addEventListener("click",()=>toggleSaved("kahoo_saved_posts",item,save,true));tile.append(link,save);posts.append(tile);
    });
    merchantDialogLoading.hidden=true;merchantDialogContent.hidden=false;
  }catch{merchantDialogLoading.textContent="اطلاعات فروشگاه دریافت نشد"}
}
document.querySelector(".merchant-dialog-close").addEventListener("click",()=>merchantDialog.close());merchantDialog.addEventListener("click",event=>{if(event.target===merchantDialog)merchantDialog.close()});
let shopRequest=0;
async function loadShops(){const request=++shopRequest,params=new URLSearchParams();if(selectedCategory)params.set("category",selectedCategory);if(query)params.set("q",query);emptyState.hidden=true;const loadingTimer=setTimeout(()=>{if(request===shopRequest)shopGrid.innerHTML=loaderMarkup("در حال دریافت فروشگاه‌ها")},120);try{const nextShops=await api(`/api/merchants?${params}`);if(request!==shopRequest)return;shops=nextShops;renderShops()}finally{clearTimeout(loadingTimer)}}
async function bootstrap(){
  try{categoryTree=await api("/api/categories");renderTree();await loadShops()}
  catch(error){resultTitle.textContent="اتصال به پایگاه داده برقرار نشد";resultCount.textContent="سرور را با python3 server.py اجرا کن";console.error(error)}
}

document.querySelector("#reset-category").addEventListener("click",()=>{selectedCategory=null;selectedLabel="";renderTree();closeCategoryMenu();loadShops()});
searchForm.addEventListener("submit",event=>{event.preventDefault();query=searchInput.value.trim();loadShops()});let searchTimer;searchInput.addEventListener("input",()=>{clearTimeout(searchTimer);query=searchInput.value.trim();searchTimer=setTimeout(loadShops,240)});

const connectDialog=document.querySelector("#connect-dialog"),connectButton=document.querySelector("#instagram-connect"),importStatus=document.querySelector("#import-status"),connectStates=[...document.querySelectorAll("[data-connect-state]")];let imported=false;
function showConnectState(name){connectStates.forEach(state=>{state.hidden=state.dataset.connectState!==name})}
document.querySelectorAll("[data-open-connect]").forEach(button=>button.addEventListener("click",()=>{showConnectState(imported?"done":"start");connectDialog.showModal()}));document.querySelector("#connect-dialog .dialog-close").addEventListener("click",()=>connectDialog.close());connectDialog.addEventListener("click",event=>{if(event.target===connectDialog)connectDialog.close()});
connectButton.addEventListener("click",async()=>{track("oauth_started");showConnectState("loading");for(const [index,step] of ["دریافت پروفایل","دریافت آخرین پست‌ها","تشخیص دسته‌بندی"].entries()){setTimeout(()=>{importStatus.textContent=step},index*550)}try{await new Promise(resolve=>setTimeout(resolve,1700));await api("/api/merchants/import-demo",{method:"POST",headers:{"Content-Type":"application/json"},body:"{}"});track("oauth_completed");imported=true;categoryTree=await api("/api/categories");await loadShops();renderTree();showConnectState("done")}catch{showConnectState("start")}});document.querySelector(".done-button").addEventListener("click",()=>{connectDialog.close();document.querySelector("#shops").scrollIntoView({behavior:"smooth"})});

const loginDialog=document.querySelector("#login-dialog"),loginTrigger=document.querySelector("#login-trigger"),phoneForm=document.querySelector("#phone-form"),otpForm=document.querySelector("#otp-form"),phoneInput=document.querySelector("#phone-input"),otpInput=document.querySelector("#otp-input");let loginPhone="",challengeId="";
const latinDigits=value=>value.replace(/[۰-۹]/g,digit=>"۰۱۲۳۴۵۶۷۸۹".indexOf(digit));
if(localStorage.getItem("kahoo_user")){loginTrigger.textContent="حساب من";loginTrigger.classList.add("logged-in")}
loginTrigger.addEventListener("click",()=>{if(loginTrigger.classList.contains("logged-in")){location.href="/saved.html";return}track("login_started");loginDialog.showModal()});document.querySelector(".login-close").addEventListener("click",()=>loginDialog.close());loginDialog.addEventListener("click",event=>{if(event.target===loginDialog)loginDialog.close()});
phoneForm.addEventListener("submit",async event=>{event.preventDefault();loginPhone=latinDigits(phoneInput.value.trim());if(!/^09\d{9}$/.test(loginPhone)){document.querySelector("#phone-error").textContent="شماره موبایل را درست وارد کن";return}const response=await api("/api/login/request",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({phone:loginPhone})});challengeId=response.challenge_id;document.querySelector("#phone-error").textContent="";document.querySelector("#phone-preview").textContent=phoneInput.value.trim();phoneForm.hidden=true;otpForm.hidden=false;otpInput.focus()});
document.querySelector(".back-button").addEventListener("click",()=>{otpForm.hidden=true;phoneForm.hidden=false;phoneInput.focus()});otpForm.addEventListener("submit",async event=>{event.preventDefault();const code=latinDigits(otpInput.value.trim());if(!/^\d{5}$/.test(code)){document.querySelector("#otp-error").textContent="کد باید ۵ رقم باشد";return}const response=await api("/api/login/verify",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({phone:loginPhone,code,challenge_id:challengeId})});track("login_completed");localStorage.setItem("kahoo_user",JSON.stringify({display_name:response.user.display_name}));loginDialog.close();location.href="/saved.html"});

bootstrap();
