package ru.elytrix.bots;

import com.mojang.authlib.GameProfile;
import org.bukkit.Bukkit;
import org.bukkit.World;

import java.lang.reflect.*;
import java.net.InetSocketAddress;
import java.net.SocketAddress;
import java.util.*;

/** Paper 1.16.5 player-list registration with a complete in-memory network stub. */
final class NmsFakePlayerRegistry {
    private final List<Object> entities = new ArrayList<>();
    private final Set<UUID> uuids = new HashSet<>();
    private final Map<UUID,Object> byUuid = new HashMap<>();
    private final Map<UUID,UUID> serverUuids=new HashMap<>();
    private List<Object> serverPlayers;
    private final Map<UUID,List<Object>> indexedCollections=new HashMap<>();
    private final Map<UUID,List<Map<Object,Object>>> indexedMaps=new HashMap<>();

    @SuppressWarnings("unchecked")
    void register(String name, UUID uuid, World world) {
        try {
            String nms = "net.minecraft.server." + Bukkit.getServer().getClass().getPackage().getName().split("\\.")[3] + ".";
            Object server = Bukkit.getServer().getClass().getMethod("getServer").invoke(Bukkit.getServer());
            Object worldServer = world.getClass().getMethod("getHandle").invoke(world);
            Class<?> mc = Class.forName(nms+"MinecraftServer"), ws=Class.forName(nms+"WorldServer");
            Class<?> interact=Class.forName(nms+"PlayerInteractManager"), entityPlayer=Class.forName(nms+"EntityPlayer");
            Object manager=interact.getConstructor(ws).newInstance(worldServer);
            UUID serverUuid=UUID.nameUUIDFromBytes(("OfflinePlayer:"+name).getBytes(java.nio.charset.StandardCharsets.UTF_8));
            Object entity=entityPlayer.getConstructor(mc,ws,GameProfile.class,interact).newInstance(server,worldServer,new GameProfile(serverUuid,name),manager);

            Class<?> direction=Class.forName(nms+"EnumProtocolDirection"), networkType=Class.forName(nms+"NetworkManager");
            Object clientbound=Arrays.stream(direction.getEnumConstants()).filter(v->v.toString().equals("CLIENTBOUND")).findFirst().orElseThrow();
            Object network=networkType.getConstructor(direction).newInstance(clientbound);
            prepareNetwork(network);
            // Скрытый NMS-двойник проходит штатную серверную процедуру входа; VirtualPlayer рисует тело.
            entity.getClass().getMethod("setInvisible",boolean.class).invoke(entity,true);
            Object list=listObject(server);entities.add(entity);uuids.add(uuid);uuids.add(serverUuid);byUuid.put(uuid,entity);serverUuids.put(uuid,serverUuid);
            Method place=list.getClass().getMethod("a",networkType,entityPlayer);
            place.invoke(list,network,entity);
            if(serverPlayers==null){Field field=list.getClass().getSuperclass().getDeclaredField("players");field.setAccessible(true);serverPlayers=(List<Object>)field.get(list);}
            indexPlayer(list,worldServer,entity,name,serverUuid);indexedCollections.put(uuid,indexedCollections.remove(serverUuid));indexedMaps.put(uuid,indexedMaps.remove(serverUuid));
        } catch (ReflectiveOperationException ex) { throw new IllegalStateException("Paper 1.16.5 fake player registration failed",ex); }
    }

    private Object listObject(Object server)throws ReflectiveOperationException{return server.getClass().getMethod("getPlayerList").invoke(server);}

    @SuppressWarnings("unchecked")
    private void indexPlayer(Object playerList,Object worldServer,Object entity,String name,UUID uuid)throws IllegalAccessException{
        List<Object> lists=new ArrayList<>();List<Map<Object,Object>> maps=new ArrayList<>();
        // CraftBukkit lookup methods and World#getPlayers use additional UUID/name maps and the world's player list.
        for(Object owner:List.of(playerList,worldServer))for(Class<?> type=owner.getClass();type!=null;type=type.getSuperclass())for(Field field:type.getDeclaredFields()){
            String generic=field.getGenericType().getTypeName();if(!generic.contains("EntityPlayer")&&!generic.contains("EntityHuman"))continue;field.setAccessible(true);Object value=field.get(owner);
            if(value instanceof List<?> raw){List<Object> list=(List<Object>)raw;if(!list.contains(entity))list.add(entity);lists.add(list);}
            else if(value instanceof Map<?,?> raw){Map<Object,Object> map=(Map<Object,Object>)raw;Object key=generic.contains("java.lang.String")?name.toLowerCase(Locale.ROOT):uuid;map.put(key,entity);maps.add(map);}
        }
        indexedCollections.put(uuid,lists);indexedMaps.put(uuid,maps);
    }

    private void prepareNetwork(Object network) throws ReflectiveOperationException {
        // Essentials/TAB access address and plugins may send packets. A null channel caused their async NPEs.
        Object channel=Class.forName("io.netty.channel.embedded.EmbeddedChannel").getConstructor().newInstance();
        for(Class<?> type=network.getClass();type!=null;type=type.getSuperclass()) for(Field field:type.getDeclaredFields()) {
            field.setAccessible(true);
            if (Class.forName("io.netty.channel.Channel").isAssignableFrom(field.getType())) field.set(network,channel);
            else if (SocketAddress.class.isAssignableFrom(field.getType())) field.set(network,new InetSocketAddress("127.0.0.1",0));
        }
    }

    void position(UUID uuid,org.by1337.blib.geom.Vec3d pos,float yaw,float pitch){Object entity=byUuid.get(uuid);if(entity==null)return;try{entity.getClass().getMethod("setPositionRotation",double.class,double.class,double.class,float.class,float.class).invoke(entity,pos.x,pos.y,pos.z,yaw,pitch);}catch(Exception ignored){}}
    boolean isFake(UUID uuid){return uuids.contains(uuid);}
    org.bukkit.entity.Player player(UUID uuid){Object entity=byUuid.get(uuid);if(entity==null)return null;try{return (org.bukkit.entity.Player)entity.getClass().getMethod("getBukkitEntity").invoke(entity);}catch(Exception ignored){return null;}}
    int size(){return entities.size();}
    void remove(UUID uuid){Object entity=byUuid.remove(uuid);if(entity!=null){try{entity.getClass().getMethod("die").invoke(entity);}catch(Exception ignored){}if(serverPlayers!=null)serverPlayers.remove(entity);List<Object> lists=indexedCollections.remove(uuid);if(lists!=null)for(Object value:lists)((List<?>)value).remove(entity);List<Map<Object,Object>> maps=indexedMaps.remove(uuid);if(maps!=null)for(Map<Object,Object> map:maps)map.values().removeIf(v->v==entity);entities.remove(entity);uuids.remove(uuid);UUID serverUuid=serverUuids.remove(uuid);if(serverUuid!=null)uuids.remove(serverUuid);}}
    void clear(){for(UUID uuid:new ArrayList<>(byUuid.keySet()))remove(uuid);entities.clear();uuids.clear();byUuid.clear();indexedCollections.clear();indexedMaps.clear();serverUuids.clear();serverPlayers=null;}
}
