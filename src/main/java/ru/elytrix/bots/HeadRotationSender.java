package ru.elytrix.bots;

import org.bukkit.entity.Player;

import java.lang.reflect.Constructor;
import java.lang.reflect.Method;
import java.util.Collection;

/** Sends a head-only rotation after VirtualEntity's body rotation packet. */
final class HeadRotationSender {
    private static Constructor<?> constructor;
    private static Method send;
    static void send(int entityId,float yaw,Collection<Player> viewers){
        try{
            if(constructor==null){Class<?> type=Class.forName("dev.by1337.virtualentity.core.network.impl.RotateHeadPacket");constructor=type.getConstructor(int.class,byte.class);send=type.getMethod("send",Player.class);}
            Object packet=constructor.newInstance(entityId,(byte)(yaw*256F/360F));
            for(Player viewer:viewers)send.invoke(packet,viewer);
        }catch(ReflectiveOperationException ignored){}
    }
}
