package ru.elytrix.bots;

import dev.by1337.virtualentity.api.virtual.player.VirtualPlayer;
import net.luckperms.api.LuckPerms;
import net.luckperms.api.LuckPermsProvider;
import net.luckperms.api.node.types.InheritanceNode;
import net.luckperms.api.model.user.User;
import net.kyori.adventure.text.serializer.legacy.LegacyComponentSerializer;
import org.bukkit.*;
import org.bukkit.block.Block;
import org.bukkit.configuration.ConfigurationSection;
import org.bukkit.configuration.file.YamlConfiguration;
import org.bukkit.command.*;
import org.bukkit.entity.Player;
import org.bukkit.event.*;
import org.bukkit.event.player.*;
import org.bukkit.event.entity.EntityDamageByEntityEvent;
import org.bukkit.event.server.ServerListPingEvent;
import org.bukkit.plugin.java.JavaPlugin;
import org.bukkit.scheduler.BukkitTask;
import org.bukkit.util.BoundingBox;
import org.by1337.blib.geom.Vec3d;

import java.io.File;
import java.util.*;

public final class ElytrixBotsPlugin extends JavaPlugin implements Listener, CommandExecutor, TabCompleter {
    private final List<VirtualPlayer> tabBots = new ArrayList<>();
    private final List<MovingBot> liveBots = new ArrayList<>();
    private BukkitTask ticker;
    private YamlConfiguration bots;
    private DatasetManager datasets;
    private final Random random = new Random();
    private final BotTeamManager teams = new BotTeamManager();
    private final NmsFakePlayerRegistry registry = new NmsFakePlayerRegistry();
    private ProxySyncSender proxySync;
    private PopulationDatabase database;
    private final Map<String,ActiveBot> active = new LinkedHashMap<>();
    private final List<BotProfile> profiles = new ArrayList<>();
    private long nextPopulationChange;
    private int dailyMinuteJitter;
    private double visibleChance;
    private boolean rooyzeeMode;
    private long nextFanMessage;
    private final Map<UUID,User> luckPermsUsers=new java.util.concurrent.ConcurrentHashMap<>();
    private final Set<String> pendingProfiles=java.util.concurrent.ConcurrentHashMap.newKeySet();
    private boolean firstPopulationChange=true;
    private int styleRefreshTicks;
    private final Map<String,HitSequence> hitSequences=new HashMap<>();
    private final Map<UUID,Long> reactionCooldowns=new HashMap<>();

    @Override public void onEnable() {
        saveDefaultConfig(); saveResource("bots.yml", false);
        bots = YamlConfiguration.loadConfiguration(new File(getDataFolder(), "bots.yml"));
        datasets = new DatasetManager(this);
        ensureProfiles();
        database = new PopulationDatabase(new File(getDataFolder(), "population.db"));
        dailyMinuteJitter=random.nextInt(91)-45;
        double visibleMin=getConfig().getDouble("population.visible-percent.min",20)/100D,visibleMax=getConfig().getDouble("population.visible-percent.max",60)/100D;visibleChance=visibleMin+random.nextDouble()*Math.max(0,visibleMax-visibleMin);
        nextPopulationChange=System.currentTimeMillis()+10000L;
        Bukkit.getPluginManager().registerEvents(this, this);
        proxySync=new ProxySyncSender(this,this::fakeCount); proxySync.start();
        PluginCommand botCommand=Objects.requireNonNull(getCommand("elytrixbots"));botCommand.setExecutor(this);botCommand.setTabCompleter(this);
        int period = Math.max(2, getConfig().getInt("settings.movement-period-ticks", 2));
        ticker = Bukkit.getScheduler().runTaskTimer(this, () -> tick(period), 1L, period);
        getLogger().info("Loaded " + tabBots.size() + " TAB and " + liveBots.size() + " live bots.");
    }

    @Override public void onDisable() {
        if (ticker != null) ticker.cancel();
        if (proxySync != null) proxySync.stop();
        for (Player viewer : realPlayers()) {
            tabBots.forEach(bot -> bot.sendRemovePlayerPacket(viewer));
            liveBots.forEach(bot -> { bot.player.tick(Collections.emptySet()); bot.player.sendRemovePlayerPacket(viewer); });
        }
        teams.clear(); registry.clear();
        tabBots.clear(); liveBots.clear(); active.clear();
        if(database!=null)database.close();
    }

    // Зарезервированные профили никогда не разрешены для настоящего сетевого входа.
    @EventHandler(priority=EventPriority.HIGHEST)
    public void onPreLogin(AsyncPlayerPreLoginEvent event){for(BotProfile profile:profiles)if(profile.name.equalsIgnoreCase(event.getName())){event.disallow(AsyncPlayerPreLoginEvent.Result.KICK_OTHER,"Этот профиль зарезервирован сервером.");return;}}

    @EventHandler public void onJoin(PlayerJoinEvent event) {
        if(!registry.isFake(event.getPlayer().getUniqueId()))Bukkit.getScheduler().runTaskLater(this, () -> sendTab(event.getPlayer()), 10L);
    }

    // Смена измерения очищает часть клиентского PlayerInfo. Возвращаем глобальный TAB после respawn-пакета.
    @EventHandler public void onWorldChange(PlayerChangedWorldEvent event){
        if(!registry.isFake(event.getPlayer().getUniqueId()))Bukkit.getScheduler().runTaskLater(this,()->sendTab(event.getPlayer()),10L);
    }
    @EventHandler public void onRespawn(PlayerRespawnEvent event){
        if(!registry.isFake(event.getPlayer().getUniqueId()))Bukkit.getScheduler().runTaskLater(this,()->sendTab(event.getPlayer()),10L);
    }
    // Всегда отдаём /near владельцу ElytrixCore, независимо от порядка регистрации Essentials.
    @EventHandler(priority=EventPriority.LOWEST)
    public void onNear(PlayerCommandPreprocessEvent event){if(!event.getMessage().equalsIgnoreCase("/near"))return;if(Bukkit.getPluginManager().getPlugin("ElytrixCore")==null)return;event.setCancelled(true);if(!Bukkit.dispatchCommand(event.getPlayer(),"elytrixcore:near"))event.getPlayer().sendMessage(elytrix("&cОшибка: &fкоманда ElytrixCore /near не зарегистрирована."));}

    @EventHandler(ignoreCancelled=true,priority=EventPriority.HIGHEST)
    public void onBotHit(EntityDamageByEntityEvent event){if(!(event.getDamager() instanceof Player attacker))return;ActiveBot hit=null;for(ActiveBot bot:active.values()){Player entity=registry.player(bot.player.getUuid());if(entity!=null&&entity.getUniqueId().equals(event.getEntity().getUniqueId())){hit=bot;break;}}if(hit==null)return;event.setCancelled(true);long now=System.currentTimeMillis();if(reactionCooldowns.getOrDefault(hit.player.getUuid(),0L)>now)return;String key=attacker.getUniqueId()+":"+hit.profile.name;HitSequence sequence=hitSequences.get(key);if(sequence==null||now-sequence.last>1400)sequence=new HitSequence(now,now);else sequence.last=now;hitSequences.put(key,sequence);if(now-sequence.started<9000)return;hitSequences.remove(key);reactionCooldowns.put(hit.player.getUuid(),now+30000);String[] replies={"чё тебе","хватит","отстань","зачем бьёшь","эй, хорош","тебе заняться нечем?","ну всё, я ушёл","не бей","я афк вообще-то","что надо?"};if(random.nextInt(4)!=0)chat(hit,replies[random.nextInt(replies.length)]);if(hit.moving!=null&&random.nextInt(5)!=0){Point point=randomSafePoint(hit.moving.world);hit.moving.setTarget(point.vector());}}
    private static final class HitSequence{final long started;long last;HitSequence(long started,long last){this.started=started;this.last=last;}}

    @EventHandler(priority = EventPriority.HIGHEST)
    public void onPing(ServerListPingEvent event) {
        if (getConfig().getBoolean("settings.motd-count-enabled", true))
            event.setMaxPlayers(Math.max(event.getMaxPlayers(), Bukkit.getOnlinePlayers().size() + 1));
        // Bukkit не позволяет менять getNumPlayers; Bungee-модуль должен менять число на proxy.
    }

    private void sendTab(Player viewer) {
        if (!viewer.isOnline()) return;
        tabBots.forEach(bot -> bot.sendAddPlayerPacket(viewer));
    }

    private int fakeCount() { return active.size(); }

    private void ensureProfiles() {
        ConfigurationSection section=bots.getConfigurationSection("profiles");
        if(section==null||bots.getInt("profiles-version",0)<5){
            bots.set("profiles",null);bots.set("profiles-version",5);
            String raw="kavol,Grom,Be1ka,peacherrka,Dimon4ik,Batmen,Arbuzer,Grizz1y,Kosmos,Legion,Rekrut,Shaman,SunnyOne,foxiee,northside,KotBegemot,JustMaks,tihohod,redstonekid,Keksik,oldminer,WaterLime,Neonix,Timoxa,Dan4ik,Kirito,GoodBoi,StalkerX,Angel05,Bober,Poisoned,Arbuzzz,FreshMan,Bratishka,WindyWay,Quasar,Lunatik,ZloyKot,Dobryak,KapitanX,Spartak,PixelMan,Monolit,Faraon,Bambuk,Severok,Reactor,Marmelad,KingSize,LuckyMan,Fastik,Medvedik,Omega7,SilentGuy,Geroy,Novichok,Knyaz,BlackFox,OrangeJuice,Kompotik,MrRobot,PlayerOne,Snowman,Raketa,Karasik,Som,Voron,Orlan,Sapsan,Baron77,Shustriy,Umnik,Molniya,Tornado,Sahara,Atlant,OrionSky,SaturnX,Marsik,KosmosKid,Avatar,Partizan,Majorik,MasterX,levsha,NoNameYet,Skif4ik,NorthWind,Kaktus,Pyatnica,Romashka,Fantik,ChillGuy,IceTea,Enotik,DarkSoul,Akula,Toporik,Samurai,Pechenka,Drakon,Cheburek,Viking,Almazik,Baton,Pluton,Marik,YaProstoYa,TurboMax,Milashka,Kriperok,EnderFox,MrSova,Lisiy,Maxwell,Deffo4ka,Volk13,AlexRus,Steve228,FoxyMine,NikitaGG,FridayMood,RedMoon,BlueBerry,GreenTea,SmallBee,BigBoss,notfound,whoami,maybealex,ordinaryguy,cloudnine,rainyday,afterdark,midnight,lowping,coffeepls,TeaMaster,one_more,zerohero,aspen,cedrik,juniper,riverstone,softwind,wildmint,graywolf,tinyfox,lostsignal,quietstep,randomguest,localman,faraway,woodenaxe,stonepick,diamondless,craftycat,sleepyowl,earlybird,lateplayer,moonwalker,sunflower,blackcoffee,mintcookie,hotpepper,coldwater,greenapple,redpanda,bluewhale,smallplanet,justhuman";
            String[] names=raw.split(",");int id=0;for(String name:names){id++;if(id%6==0&&!name.matches(".*\\d.*")&&name.length()<13)name+=10+random.nextInt(990);String key=String.format("bot%03d",id);bots.set("profiles."+key+".name",name);bots.set("profiles."+key+".group","default");bots.set("profiles."+key+".ping",25+random.nextInt(100));}
            try{bots.save(new File(getDataFolder(),"bots.yml"));}catch(Exception ex){getLogger().warning("Cannot save profiles: "+ex.getMessage());}
            section=bots.getConfigurationSection("profiles");
        }
        if(section!=null)for(String key:section.getKeys(false)){ConfigurationSection c=section.getConfigurationSection(key);if(c!=null)profiles.add(new BotProfile(c.getString("name",key),c.getString("group","default"),c.getInt("ping",50)));}
        getLogger().info("Loaded "+profiles.size()+" reserve bot profiles.");
    }

    private void populationTick(){
        long now=System.currentTimeMillis();
        if(rooyzeeMode&&now>=nextFanMessage&&!active.isEmpty()){sendFanMessage();nextFanMessage=now+(30+random.nextInt(91))*1000L;}
        List<ActiveBot> expired=new ArrayList<>();for(ActiveBot bot:active.values())if(bot.expiresAt<=now)expired.add(bot);for(ActiveBot bot:expired)deactivate(bot);
        if(now<nextPopulationChange)return;int target=populationTarget(),automatic=automaticCount();
        if(firstPopulationChange){if(automatic<target)activateOne();firstPopulationChange=false;}
        else if(automatic<target){activateOne();if(target-automatic>1&&random.nextInt(4)==0)Bukkit.getScheduler().runTaskLater(this,this::activateOne,40+random.nextInt(161));}
        else if(automatic>target){ActiveBot bot=randomAutomatic();if(bot!=null)deactivate(bot);}
        else if(automatic>0&&random.nextInt(7)==0){ActiveBot bot=randomAutomatic();if(bot!=null)deactivate(bot);Bukkit.getScheduler().runTaskLater(this,this::activateOne,1200+random.nextInt(2401));}
        reconcileVisible();
        // Неровные смешанные изменения онлайна раз в 2–18 минут.
        nextPopulationChange=now+(120+random.nextInt(961))*1000L;
    }
    private int automaticCount(){int count=0;for(ActiveBot bot:active.values())if(!bot.manual)count++;return count;}
    private ActiveBot randomAutomatic(){List<ActiveBot> list=new ArrayList<>();for(ActiveBot bot:active.values())if(!bot.manual)list.add(bot);return list.isEmpty()?null:list.get(random.nextInt(list.size()));}
    private int populationTarget(){
        int real=realPlayers().size();if(real==0)return 2+random.nextInt(3);
        java.time.ZonedDateTime time=java.time.ZonedDateTime.now(java.time.ZoneId.of("Europe/Moscow")).plusMinutes(dailyMinuteJitter);int hour=time.getHour();
        double low=hour<7?.30:hour<16?.38:.48,high=hour<7?.42:hour<16?.52:.60;
        return Math.max(1,Math.min(16,(int)Math.round(real*(low+random.nextDouble()*(high-low)))));
    }
    private int visibleTarget(){int real=realPlayers().size();if(real<=3)return Math.min(1,active.size());if(real<=6)return Math.min(2,active.size());return Math.min(3+random.nextInt(2),active.size());}
    private void reconcileVisible(){int wanted=visibleTarget(),current=0;for(ActiveBot bot:active.values())if(!bot.manual&&bot.moving!=null)current++;while(current>wanted){for(ActiveBot bot:active.values())if(!bot.manual&&bot.moving!=null){liveBots.remove(bot.moving);bot.moving.player.tick(Collections.emptySet());bot.moving=null;current--;break;}}if(current<wanted){for(ActiveBot bot:active.values())if(!bot.manual&&bot.moving==null){Player entity=registry.player(bot.player.getUuid());if(entity==null)continue;Point point=randomSafePoint(entity.getWorld());bot.moving=new MovingBot(bot.player,point.world(),point.vector(),3.4+random.nextDouble());liveBots.add(bot.moving);if(++current>=wanted)break;}}}
    private void activateOne(){activateOne(false,false);}
    private boolean activateOne(boolean manual,boolean visible){
        long now=System.currentTimeMillis();List<BotProfile> available=new ArrayList<>();for(BotProfile p:profiles)if(!active.containsKey(p.name)&&!pendingProfiles.contains(p.name)&&(manual||database.cooldown(p.name)<=now))available.add(p);if(available.isEmpty())return false;
        BotProfile profile=available.get(random.nextInt(available.size()));pendingProfiles.add(profile.name);Location spawn=spawn(null);VirtualPlayer player=create(profile.name,profile.ping,profile.group,spawn.getWorld());
        if(Bukkit.getPluginManager().isPluginEnabled("LuckPerms"))try{LuckPerms lp=LuckPermsProvider.get();UUID uuid=UUID.nameUUIDFromBytes(("OfflinePlayer:"+profile.name).getBytes(java.nio.charset.StandardCharsets.UTF_8));lp.getUserManager().savePlayerData(uuid,profile.name).thenCompose(result->lp.getUserManager().loadUser(uuid,profile.name)).thenAccept(user->{user.data().add(InheritanceNode.builder(profile.group).build());lp.getUserManager().saveUser(user);Bukkit.getScheduler().runTask(this,()->finishActivation(profile,manual,visible,user,player,spawn));}).exceptionally(error->{pendingProfiles.remove(profile.name);teams.remove(profile.name);getLogger().warning("LuckPerms profile failed: "+error.getMessage());return null;});return true;}catch(Exception ignored){}
        finishActivation(profile,manual,visible,null,player,spawn);return true;
    }
    private void finishActivation(BotProfile profile,boolean manual,boolean visible,User preparedUser,VirtualPlayer player,Location spawn){
        pendingProfiles.remove(profile.name);if(active.containsKey(profile.name))return;long now=System.currentTimeMillis();player.setPos(vec(spawn));player.setYaw(spawn.getYaw());player.setPitch(spawn.getPitch());player.setOnGround(true);if(preparedUser!=null)luckPermsUsers.put(player.getUuid(),preparedUser);registry.register(profile.name,player.getUuid(),spawn.getWorld());
        registry.position(player.getUuid(),vec(spawn),spawn.getYaw(),spawn.getPitch());tabBots.add(player);realPlayers().forEach(player::sendAddPlayerPacket);MovingBot moving=null;if(visible){Point point=randomSafePoint(spawn.getWorld());moving=new MovingBot(player,spawn.getWorld(),point.vector(),3.4+random.nextDouble());liveBots.add(moving);}
        long expires=manual?Long.MAX_VALUE:now+randomMinutes("population.session-minutes",60,360)*60000L;ActiveBot activated=new ActiveBot(profile,player,moving,expires,manual);active.put(profile.name,activated);getLogger().info(profile.name+" joined"+(manual?" manually":"")+" ("+active.size()+" bots online)");
        // Временная проверка полного глобального чата после регистрации всех плагинов.
        Bukkit.getScheduler().runTaskLater(this,()->{if(active.get(profile.name)==activated)chat(activated,"!1");},60L);
    }
    private void deactivate(ActiveBot bot){
        for(Player viewer:realPlayers()){bot.player.sendRemovePlayerPacket(viewer);}if(bot.moving!=null){bot.player.tick(Collections.emptySet());liveBots.remove(bot.moving);}tabBots.remove(bot.player);registry.remove(bot.player.getUuid());teams.remove(bot.profile.name);User lpUser=luckPermsUsers.remove(bot.player.getUuid());if(lpUser!=null)try{LuckPermsProvider.get().getUserManager().cleanupUser(lpUser);}catch(Exception ignored){}active.remove(bot.profile.name);database.quit(bot.profile.name,System.currentTimeMillis()+randomMinutes("population.profile-cooldown-minutes",120,360)*60000L);getLogger().info(bot.profile.name+" left ("+active.size()+" bots online)");
    }
    private Point randomSafePoint(World world){
        for(int attempt=0;attempt<80;attempt++){double centerX=getConfig().getDouble("population.region.center-x",30),centerZ=getConfig().getDouble("population.region.center-z",9),radius=Math.min(30,getConfig().getDouble("population.region.radius",30));double x=centerX+(random.nextDouble()*2-1)*radius,z=centerZ+(random.nextDouble()*2-1)*radius;for(int y=Math.min(world.getMaxHeight()-2,world.getHighestBlockYAt((int)x,(int)z)+1);y>world.getMinHeight();y--){Block floor=world.getBlockAt((int)Math.floor(x),y-1,(int)Math.floor(z));if(!floor.isPassable()&&!unsafeFloor(floor)&&world.getBlockAt((int)x,y,(int)z).isPassable()&&world.getBlockAt((int)x,y+1,(int)z).isPassable())return new Point(world,x+.5,y,z+.5,0,0);}}
        Location fallback=world.getSpawnLocation();return new Point(world,fallback.getX(),fallback.getY(),fallback.getZ(),fallback.getYaw(),fallback.getPitch());
    }
    private void startFanConversation(){
        Bukkit.getScheduler().runTaskLater(this,()->{
            List<ActiveBot> list=new ArrayList<>(active.values());if(list.isEmpty())return;chat(list.get(random.nextInt(list.size())),"Кто смотрит rooyzee?");
            Collections.shuffle(list);String[] replies={"я","я смотрю","я со стрима","тоже смотрю","я его фанат","тут все со стрима?","розю смотрю"};
            int delay=35;for(ActiveBot bot:list){String reply=replies[random.nextInt(replies.length)];Bukkit.getScheduler().runTaskLater(this,()->chat(bot,reply),delay);delay+=20+random.nextInt(41);}
        },80L);
    }
    private void sendFanMessage(){
        List<ActiveBot> list=new ArrayList<>(active.values());if(list.isEmpty())return;
        String[] starts={"я со стрима","я его фанат","роузи дай админку","розяка привет","я на стриме","когда видос","фу игноришь","кто с трансляции","давно смотрю","новый ролик топ","розю кто видел","на стриме веселее","привет всем фанатам","я только зашёл","это тот сервер?"};
        String[] tails={""," ахах"," кстати"," реально"," пж","))","!","?"," уже давно"," сегодня"," отвечай"," го вместе"," кто тоже?"," лол"," наконец-то"};
        chat(list.get(random.nextInt(list.size())),starts[random.nextInt(starts.length)]+tails[random.nextInt(tails.length)]);
    }
    private void chat(ActiveBot bot,String message){Player sender=registry.player(bot.player.getUuid());if(sender!=null)sender.chat(message.startsWith("!")?message:"!"+message);}

    private boolean unsafeFloor(Block block){String m=block.getType().name();return m.contains("LEAVES")||m.contains("LOG")||m.contains("CARPET")||m.contains("WATER")||m.contains("LAVA")||m.contains("FENCE")||m.contains("WALL");}
    private long randomMinutes(String path,int fallbackMin,int fallbackMax){int min=getConfig().getInt(path+".min",fallbackMin),max=Math.max(min,getConfig().getInt(path+".max",fallbackMax));return min+random.nextInt(max-min+1);}
    private record BotProfile(String name,String group,int ping){}
    private static final class ActiveBot{final BotProfile profile;final VirtualPlayer player;MovingBot moving;final long expiresAt;final boolean manual;ActiveBot(BotProfile p,VirtualPlayer v,MovingBot m,long e,boolean manual){profile=p;player=v;moving=m;expiresAt=e;this.manual=manual;}}

    private VirtualPlayer create(String name, int ping, String group, World registrationWorld) {
        if (name.isBlank() || name.length() > 16) throw new IllegalArgumentException("name must be 1-16 characters");
        VirtualPlayer p = VirtualPlayer.create(); p.setName(name); p.setLatency(Math.max(0, ping)); p.setGameMode(GameMode.SURVIVAL);
        BotTeamManager.Style style=teams.add(name, group, getConfig().getString("formatting.default-suffix", " &dБЕТА"));
        String label=style.prefix()+ChatColor.GRAY+name+style.suffix();
        p.setDisplayName(LegacyComponentSerializer.legacySection().deserialize(label));
        return p;
    }

    private void refreshStyles(){if(!Bukkit.getPluginManager().isPluginEnabled("LuckPerms"))return;for(ActiveBot bot:active.values()){User user=luckPermsUsers.get(bot.player.getUuid());if(user==null)continue;String group=user.getPrimaryGroup();teams.remove(bot.profile.name);BotTeamManager.Style style=teams.add(bot.profile.name,group,getConfig().getString("formatting.default-suffix"," &dБЕТА"));String label=style.prefix()+ChatColor.GRAY+bot.profile.name+style.suffix();bot.player.setDisplayName(LegacyComponentSerializer.legacySection().deserialize(label));for(Player viewer:realPlayers())bot.player.sendAddPlayerPacket(viewer);}}

    private List<Player> realPlayers() {
        List<Player> result = new ArrayList<>();
        for (Player player : Bukkit.getOnlinePlayers()) if (!registry.isFake(player.getUniqueId())) result.add(player);
        return result;
    }

    private void tick(int ticks) {
        datasets.tick(); populationTick();if(++styleRefreshTicks>=50){styleRefreshTicks=0;refreshStyles();}
        // Список зрителей строится один раз на мир, а не отдельно для каждого бота.
        Map<World,Set<Player>> viewersByWorld=new HashMap<>();
        for(Player player:realPlayers())viewersByWorld.computeIfAbsent(player.getWorld(),w->new HashSet<>()).add(player);
        for(MovingBot b:liveBots){b.move(ticks/20D);registry.position(b.player.getUuid(),b.player.getPos(),b.player.getYaw(),b.player.getPitch());b.player.tick(viewersByWorld.getOrDefault(b.world,Collections.emptySet()));}
    }

    @Override public boolean onCommand(CommandSender sender, Command command, String label, String[] args) {
        if (!(sender instanceof Player player)) { sender.sendMessage("Player only"); return true; }
        if (!player.hasPermission("elytrixbots.dataset")) { player.sendMessage(elytrix("&cОшибка: &fнедостаточно прав.")); return true; }
        if(args.length==0){
            player.sendMessage(elytrix("&#F8BEFBКоманды"));
            player.sendMessage(color("&#F8BEFB&l┃ &f/elytrixbots online &7— онлайн"));
            player.sendMessage(color("&#F8BEFB&l┃ &f/elytrixbots rooyzee &7— режим фанатов"));
            player.sendMessage(color("&#F8BEFB&l┃ &f/elytrixbots kick <ник> &7— отключить бота"));
            player.sendMessage(color("&#F8BEFB&l┃ &f/elytrixbots connect <tab|live> <кол-во> <секунды>"));
            player.sendMessage(color("&#F8BEFB&l┃ &f/elytrixbots dataset &7— запись движений"));return true;
        }
        if(args.length==1&&args[0].equalsIgnoreCase("online")){int real=realPlayers().size(),fake=active.size();player.sendMessage(elytrix("&#F8BEFBОнлайн"));player.sendMessage(color("&#F8BEFB&l┃ &fРеальных: &#F8BEFB"+real));player.sendMessage(color("&#F8BEFB&l┃ &fБотов: &#F8BEFB"+fake));player.sendMessage(color("&#F8BEFB&l┃ &fВсего: &#F8BEFB"+(real+fake)));return true;}
        if(args.length==2&&args[0].equalsIgnoreCase("kick")){ActiveBot found=null;for(ActiveBot bot:active.values())if(bot.profile.name.equalsIgnoreCase(args[1])){found=bot;break;}if(found==null){player.sendMessage(elytrix("&cОшибка: &fбот не найден."));return true;}String name=found.profile.name;deactivate(found);player.sendMessage(elytrix("&aБот отключён: &#F8BEFB"+name));return true;}
        if(args.length==4&&args[0].equalsIgnoreCase("connect")){boolean live=args[1].equalsIgnoreCase("live");if(!live&&!args[1].equalsIgnoreCase("tab")){player.sendMessage(elytrix("&cОшибка: &fтип должен быть tab или live."));return true;}try{int amount=Integer.parseInt(args[2]);if(amount<1||amount>profiles.size())throw new NumberFormatException();String[] range=args[3].split("-",-1);int min=Integer.parseInt(range[0]),max=range.length==1?min:Integer.parseInt(range[1]);if(range.length>2||min<0||max<min)throw new NumberFormatException();for(int i=0;i<amount;i++){long delay=(min==max?min:min+random.nextInt(max-min+1))*20L;Bukkit.getScheduler().runTaskLater(this,()->activateOne(true,live),delay);}player.sendMessage(elytrix("&aЗапланировано: &#F8BEFB"+amount+" &fботов &7("+min+(min==max?"":"–"+max)+" сек.)"));}catch(NumberFormatException ex){player.sendMessage(elytrix("&cОшибка: &fпример: /elytrixbots connect live 5 10-2000"));}return true;}
        if(args.length==1&&args[0].equalsIgnoreCase("rooyzee")){rooyzeeMode=!rooyzeeMode;nextFanMessage=System.currentTimeMillis()+15000;if(rooyzeeMode)startFanConversation();player.sendMessage(elytrix(rooyzeeMode?"&aРежим фанатов rooyzee включён.":"&cРежим фанатов rooyzee выключен."));return true;}
        if (args.length >= 3 && args[0].equalsIgnoreCase("dataset") && args[1].equalsIgnoreCase("start")) {
            String name=args.length>=4?args[3]:String.valueOf(System.currentTimeMillis()/1000);
            if (datasets.start(player, args[2].equalsIgnoreCase("all")?"всё":args[2].toLowerCase(Locale.ROOT),name)) player.sendMessage(ChatColor.GREEN + "Запись «"+args[2]+"» началась.");
            else player.sendMessage(ChatColor.RED + "Выбери тип через TAB или останови текущую запись.");
            return true;
        }
        if (args.length >= 2 && args[0].equalsIgnoreCase("dataset") && args[1].equalsIgnoreCase("stop")) {
            String result=datasets.stop(player);
            player.sendMessage(result == null ? ChatColor.RED + "Запись не запущена." : ChatColor.GREEN + "Сохранено: " + result);
            return true;
        }
        player.sendMessage(ChatColor.YELLOW + "/elytrixbots dataset start <тип> [имя] | stop"); return true;
    }

    @Override public List<String> onTabComplete(CommandSender sender,Command command,String alias,String[] args){
        if(args.length==1)return filter(List.of("online","rooyzee","connect","kick","dataset"),args[0]);
        if(args.length==2&&args[0].equalsIgnoreCase("connect"))return filter(List.of("tab","live"),args[1]);
        if(args.length==3&&args[0].equalsIgnoreCase("connect"))return filter(List.of("1","5","10"),args[2]);
        if(args.length==4&&args[0].equalsIgnoreCase("connect"))return filter(List.of("0","10","10-2000"),args[3]);
        if(args.length==2&&args[0].equalsIgnoreCase("kick")){List<String> names=new ArrayList<>();for(ActiveBot bot:active.values())names.add(bot.profile.name);return filter(names,args[1]);}
        if(args.length==2&&args[0].equalsIgnoreCase("dataset"))return filter(List.of("start","stop"),args[1]);
        if(args.length==3&&args[0].equalsIgnoreCase("dataset")&&args[1].equalsIgnoreCase("start"))return filter(DatasetManager.TYPES,args[2]);
        if(args.length==4&&args[1].equalsIgnoreCase("start"))return List.of("пример_1");
        return Collections.emptyList();
    }
    private String elytrix(String text){return color("&f☁ &#F8BEFBᴇ&#F6BEFBʟ&#F3BEFBʏ&#F1BFFBᴛ&#EEBFFBʀ&#ECBFFBɪ&#E9BFFBx &7» &f"+text);}
    private String color(String value){java.util.regex.Matcher m=java.util.regex.Pattern.compile("&#([A-Fa-f0-9]{6})").matcher(value);StringBuffer out=new StringBuffer();while(m.find()){StringBuilder rgb=new StringBuilder("§x");for(char c:m.group(1).toCharArray())rgb.append('§').append(c);m.appendReplacement(out,java.util.regex.Matcher.quoteReplacement(rgb.toString()));}m.appendTail(out);return ChatColor.translateAlternateColorCodes('&',out.toString());}
    private List<String> filter(List<String> values,String input){String q=input.toLowerCase(Locale.ROOT);List<String> result=new ArrayList<>();for(String value:values)if(value.startsWith(q))result.add(value);return result;}


    private Location spawn(ConfigurationSection explicit) {
        if (explicit != null) { Point p = point(explicit, null); return new Location(p.world, p.x, p.y, p.z, p.yaw, p.pitch); }
        if (getConfig().getBoolean("settings.use-essentials-spawn", true)) {
            File f = new File("plugins/Essentials/spawn.yml");
            if (f.isFile()) {
                ConfigurationSection s = YamlConfiguration.loadConfiguration(f).getConfigurationSection("spawns.default");
                if (s != null) {
                    World w = Bukkit.getWorld(s.getString("world-name", "world"));
                    if (w != null) return new Location(w, s.getDouble("x"), s.getDouble("y"), s.getDouble("z"), (float)s.getDouble("yaw"), (float)s.getDouble("pitch"));
                }
            }
        }
        return Bukkit.getWorlds().get(0).getSpawnLocation();
    }

    private Point point(ConfigurationSection c, World fallback) {
        if (c == null) throw new IllegalArgumentException("missing target");
        World w = c.contains("world") ? Bukkit.getWorld(c.getString("world", "world")) : fallback;
        if (w == null) throw new IllegalArgumentException("world not found");
        return new Point(w, c.getDouble("x"), c.getDouble("y"), c.getDouble("z"), (float)c.getDouble("yaw"), (float)c.getDouble("pitch"));
    }
    private static Vec3d vec(Location l) { return new Vec3d(l.getX(), l.getY(), l.getZ()); }
    private record Point(World world,double x,double y,double z,float yaw,float pitch) { Vec3d vector(){return new Vec3d(x,y,z);} }

    private final class MovingBot {
        final VirtualPlayer player; final World world; Vec3d target; final double speed; List<Vec3d> route;
        final double moveFactor=.96+random.nextDouble()*.08,turnFactor=.90+random.nextDouble()*.20;
        final float learnedTurn=datasets.learnedTurnSpeed()*(float)turnFactor;
        List<DatasetManager.MotionSample> sequence=Collections.emptyList();int frame,idleCooldown,routeIndex,jumpCooldown,stuckTicks,ambientCooldown=100+random.nextInt(301),ambientTicks,spawnDelay=40+random.nextInt(121);boolean arrived,airborneLastTick,ambientJump,afkPoseSet;double verticalVelocity,airborneStartY,velocityX,velocityZ;float lookYaw,lookPitch,ambientYaw,ambientPitch,idleTurnSpeed=3;double currentPace=1,targetPace=1;int paceTicks;long afkUntil;Vec3d lastProgressPos;
        MovingBot(VirtualPlayer p,World w,Vec3d t,double s){player=p;world=w;target=t;speed=Math.max(.1,s);route=GridPathfinder.find(w,p.getPos(),t);lookYaw=p.getYaw();lookPitch=p.getPitch();lastProgressPos=p.getPos();}
        void setTarget(Vec3d next){target=next;route=GridPathfinder.find(world,player.getPos(),target);routeIndex=0;arrived=false;afkPoseSet=false;spawnDelay=20+random.nextInt(61);stuckTicks=0;lastProgressPos=player.getPos();}
        DatasetManager.MotionSample next(){if(sequence.isEmpty()){sequence=datasets.randomSequence(random);if(sequence.isEmpty())return null;frame=random.nextInt(sequence.size());}return sequence.get(frame++%sequence.size());}
        void move(double seconds){
            Vec3d p=player.getPos();
            if(jumpCooldown>0)jumpCooldown--;
            if(spawnDelay-->0){applyPhysics(p,p.x,p.z,seconds);if(spawnDelay==10)lookYaw+=35-random.nextInt(71);smoothLook();return;}
            if(arrived){applyPhysics(p,p.x,p.z,seconds);idleBehavior();if(System.currentTimeMillis()>=afkUntil){Point point=randomSafePoint(world);setTarget(point.vector());}return;}
            DatasetManager.MotionSample sample=next();if(sample==null)sample=DatasetManager.MotionSample.neutral();
            Vec3d waypoint=routeIndex<route.size()?route.get(routeIndex):target;
            double dx=waypoint.x-p.x,dz=waypoint.z-p.z,distance=Math.hypot(dx,dz);
            if(distance<.22){
                if(routeIndex<route.size()){
                    routeIndex++;
                    if(routeIndex>=route.size()&&Math.hypot(target.x-p.x,target.z-p.z)>.6){route=GridPathfinder.find(world,p,target);routeIndex=0;}
                    return;
                }
                if(Math.hypot(target.x-p.x,target.z-p.z)>.6){route=GridPathfinder.find(world,p,target);routeIndex=0;return;}
                arrived=true;afkUntil=System.currentTimeMillis()+randomMinutes("population.afk-minutes",5,60)*60000L;player.setSprinting(false);idleBehavior();return;
            }
            if(ambientTicks>0)ambientTicks--;else{ambientYaw=approach(ambientYaw,0,.35F);ambientPitch=approach(ambientPitch,0,.25F);if(--ambientCooldown<=0){ambientTicks=20+random.nextInt(41);ambientYaw=(random.nextBoolean()?1:-1)*(5+random.nextFloat()*13);ambientPitch=-5+random.nextFloat()*10;ambientJump=random.nextInt(4)==0;ambientCooldown=120+random.nextInt(481);}}
            float desired=(float)Math.toDegrees(Math.atan2(-dx,dz))+ambientYaw;
            float turnLimit=Math.max(1.2F,Math.min(learnedTurn,learnedTurn*(.65F+Math.min(.35F,Math.abs(sample.yawDelta)/20F))));
            player.setYaw(approachAngle(player.getYaw(),desired,turnLimit));
            player.setPitch(approach(player.getPitch(),Math.max(-90,Math.min(90,ambientPitch+sample.pitchDelta*(float)turnFactor*.03F)),.8F));
            // Сначала полностью разворачиваемся, только потом начинаем идти — движения задом не будет.
            // Небольшие и средние повороты выполняются на ходу; стоим только если цель почти за спиной.
            if(Math.abs(angleDifference(player.getYaw(),desired))>85F){player.setSprinting(false);applyPhysics(p,p.x,p.z,seconds);return;}
            if(paceTicks--<=0){targetPace=.82+random.nextDouble()*.34;paceTicks=40+random.nextInt(121);}
            currentPace+=Math.max(-.008,Math.min(.008,targetPace-currentPace));
            double amount=Math.min(distance,speed*seconds*moveFactor*currentPace);
            double dirX=dx/distance,dirZ=dz/distance;
            // Реальное A/D из dataset добавляется как небольшая боковая составляющая, а не зигзаг маршрута.
            double strafe=Math.max(-.16,Math.min(.16,sample.strafe/Math.max(.01,sample.horizontal)));
            double wishX=dirX+dirZ*strafe,wishZ=dirZ-dirX*strafe,norm=Math.hypot(wishX,wishZ);wishX=wishX/norm*amount;wishZ=wishZ/norm*amount;
            // Плавное ускорение и торможение как у управляемого игрока.
            double acceleration=Math.max(.008,amount*.14);
            velocityX=approachDouble(velocityX,wishX,acceleration);velocityZ=approachDouble(velocityZ,wishZ,acceleration);
            double nx=p.x+velocityX,nz=p.z+velocityZ;
            double currentGround=groundY(p.x,p.y,p.z),aheadGround=groundY(nx,p.y,nz);
            if(Double.isNaN(currentGround)){emergencyGround(p,seconds);return;}
            boolean grounded=p.y<=currentGround+.04&&verticalVelocity<=0;
            // Смотрим дальше собственного шага и начинаем прыжок до столкновения с гранью блока.
            double probeX=p.x+dx/distance*.68,probeZ=p.z+dz/distance*.68,probeGround=groundY(probeX,p.y,probeZ);
            if(!Double.isNaN(probeGround)&&probeGround-currentGround>.75&&grounded&&jumpCooldown==0){verticalVelocity=Math.min(.48,Math.max(.44,datasets.learnedJumpVelocity(seconds)/20D));jumpCooldown=12;}
            else if(ambientJump&&grounded&&!Double.isNaN(probeGround)&&Math.abs(probeGround-currentGround)<.08&&jumpCooldown==0){verticalVelocity=.42;jumpCooldown=12;ambientJump=false;}
            // Плиты проходим прямо, но никогда не отключаем точную проверку коллизии при спуске.
            if(Double.isNaN(aheadGround)||hazardAt(nx,aheadGround,nz)||!clearAt(nx,Math.max(p.y,aheadGround),nz)){nx=p.x;nz=p.z;velocityX=velocityZ=0;aheadGround=currentGround;}
            if(aheadGround-currentGround>.75&&p.y<aheadGround-.88){nx=p.x;nz=p.z;velocityX=velocityZ=0;}
            player.setShiftKeyDown(sample.sneak);player.setSprinting(false);
            applyPhysics(p,nx,nz,seconds);
            if(Math.hypot(p.x-lastProgressPos.x,p.z-lastProgressPos.z)>.20){lastProgressPos=p;stuckTicks=0;}
            else if(++stuckTicks>45){
                // Выход из углубления: перестраиваем путь и выполняем один обычный прыжок, если зажаты блоками.
                route=GridPathfinder.find(world,player.getPos(),target);routeIndex=0;stuckTicks=0;lastProgressPos=player.getPos();
                Vec3d now=player.getPos();double floor=groundY(now.x,now.y,now.z);
                if(!Double.isNaN(floor)&&now.y<=floor+.04&&jumpCooldown==0){verticalVelocity=.42;jumpCooldown=12;}
            }
        }
        void applyPhysics(Vec3d p,double nx,double nz,double seconds){
            double ground=supportY(nx,p.y,nz);if(Double.isNaN(ground)){emergencyGround(p,seconds);return;}
            double ny=p.y;boolean grounded=p.y<=ground+.025&&verticalVelocity<=0;
            if(grounded&&ground>=p.y-.025&&ground-p.y<=.60){ny=ground;verticalVelocity=0;}
            else {
                int elapsed=Math.max(1,(int)Math.round(seconds*20));
                for(int i=0;i<elapsed;i++){ny+=verticalVelocity;verticalVelocity=(verticalVelocity-.08)*.98;}
                if(ny<=ground){ny=ground;verticalVelocity=0;}
            }
            boolean onGround=Math.abs(ny-ground)<.025;
            player.setOnGround(onGround);player.setPos(new Vec3d(nx,ny,nz));
            if(!airborneLastTick&&!onGround)airborneStartY=p.y;
            if(airborneLastTick&&onGround&&!arrived&&airborneStartY-ny>.75){route=GridPathfinder.find(world,new Vec3d(nx,ny,nz),target);routeIndex=0;stuckTicks=0;lastProgressPos=new Vec3d(nx,ny,nz);}
            airborneLastTick=!onGround;
        }
        void idleBehavior(){player.setShiftKeyDown(false);player.setSprinting(false);if(!afkPoseSet){DatasetManager.MotionSample sample=datasets.idleSample(random);float yaw=Math.abs(sample.yawDelta)<1?-28+random.nextFloat()*56:sample.yawDelta;float pitch=Math.abs(sample.pitchDelta)<1?-11+random.nextFloat()*22:sample.pitchDelta;lookYaw=player.getYaw()+yaw*(float)turnFactor;lookPitch=Math.max(-25,Math.min(25,player.getPitch()+pitch*(float)turnFactor));idleTurnSpeed=2.5F+random.nextFloat()*6F;afkPoseSet=true;}smoothLook();}
        void smoothLook(){float turn=arrived?idleTurnSpeed:Math.max(1.5F,learnedTurn*.5F);player.setYaw(approachAngle(player.getYaw(),lookYaw,turn));player.setPitch(approach(player.getPitch(),lookPitch,arrived?Math.max(1F,idleTurnSpeed*.55F):2F));}
        double approachDouble(double from,double to,double max){return from+Math.max(-max,Math.min(max,to-from));}
        float approach(float from,float to,float max){return from+Math.max(-max,Math.min(max,to-from));}
        float approachAngle(float from,float to,float max){float d=angleDifference(from,to);return from+Math.max(-max,Math.min(max,d));}
        float angleDifference(float from,float to){float d=to-from;while(d>180)d-=360;while(d<-180)d+=360;return d;}
        boolean realObstacleAhead(Vec3d p){
            Vec3d waypoint=routeIndex<route.size()?route.get(routeIndex):target;double dx=waypoint.x-p.x,dz=waypoint.z-p.z,d=Math.hypot(dx,dz);if(d<.01)return false;
            double current=groundY(p.x,p.y,p.z),ahead=groundY(p.x+dx/d*.68,p.y,p.z+dz/d*.68);return !Double.isNaN(current)&&!Double.isNaN(ahead)&&ahead-current>.75;
        }
        boolean clearAt(double x,double y,double z){
            BoundingBox body=new BoundingBox(x-.29,y+.001,z-.29,x+.29,y+1.79,z+.29);
            for(int bx=(int)Math.floor(x-.29);bx<=(int)Math.floor(x+.29);bx++)for(int bz=(int)Math.floor(z-.29);bz<=(int)Math.floor(z+.29);bz++)for(int by=(int)Math.floor(y);by<=(int)Math.floor(y+1.79);by++){
                Block block=world.getBlockAt(bx,by,bz);if(!block.isPassable()&&block.getBoundingBox().overlaps(body))return false;
            }return true;
        }
        boolean hazardAt(double x,double y,double z){return hazard(world.getBlockAt((int)Math.floor(x),(int)Math.floor(y-.01),(int)Math.floor(z)));}
        boolean hazard(Block block){String type=block.getType().name();if(getConfig().getBoolean("settings.physics.avoid-liquids",true)&&(type.contains("WATER")||type.contains("LAVA")))return true;return getConfig().getBoolean("settings.physics.avoid-hazards",true)&&(type.contains("FIRE")||type.contains("CACTUS")||type.contains("MAGMA")||type.contains("CAMPFIRE"));}
        void emergencyGround(Vec3d p,double seconds){player.setSprinting(false);if(!getConfig().getBoolean("settings.physics.anti-flight",true))return;if(p.y<=world.getMinHeight()+1){player.setPos(vec(world.getSpawnLocation()));verticalVelocity=0;return;}double ny=p.y;int elapsed=Math.max(1,(int)Math.round(seconds*20));for(int i=0;i<elapsed;i++){ny+=verticalVelocity;verticalVelocity=(verticalVelocity-.08)*.98;}player.setPos(new Vec3d(p.x,ny,p.z));player.setOnGround(false);}
        double supportY(double x,double y,double z){
            double best=Double.NaN;double[] offsets={0,-.28,.28};
            for(double ox:offsets)for(double oz:offsets){double value=groundY(x+ox,y,z+oz);if(!Double.isNaN(value)&&value<=y+.60&&(Double.isNaN(best)||value>best))best=value;}
            return best;
        }
        double groundY(double x,double y,double z){
            if(!getConfig().getBoolean("settings.physics.enabled",true))return y;int bx=(int)Math.floor(x),bz=(int)Math.floor(z),base=(int)Math.floor(y),up=getConfig().getInt("settings.physics.max-step-height",1),down=getConfig().getInt("settings.physics.max-fall-check",64);
            for(int by=base+up-1;by>=Math.max(world.getMinHeight(),base-down-1);by--){Block floor=world.getBlockAt(bx,by,bz);if(floor.isPassable())continue;double top=floor.getBoundingBox().getMaxY();if(top<=1.5)top+=by;int feet=(int)Math.ceil(top);if(world.getBlockAt(bx,feet,bz).isPassable()&&world.getBlockAt(bx,feet+1,bz).isPassable())return top;}return Double.NaN;
        }
    }
}