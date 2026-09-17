package ru.elytrix.bots.bungee;

import net.md_5.bungee.api.ProxyServer;
import net.md_5.bungee.api.ServerPing;
import net.md_5.bungee.api.event.ProxyPingEvent;
import net.md_5.bungee.api.plugin.Listener;
import net.md_5.bungee.api.plugin.Plugin;
import net.md_5.bungee.config.Configuration;
import net.md_5.bungee.config.ConfigurationProvider;
import net.md_5.bungee.config.YamlConfiguration;
import net.md_5.bungee.event.EventHandler;

import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.concurrent.atomic.AtomicInteger;

public final class ElytrixBotsBungee extends Plugin implements Listener {
    private final AtomicInteger fakeOnline=new AtomicInteger();
    private volatile boolean running;
    private DatagramSocket socket;
    private String secret;
    private long lastUpdate;

    @Override public void onEnable() {
        try { loadConfig(); } catch(IOException ex) { throw new RuntimeException("Cannot load config",ex); }
        ProxyServer.getInstance().getPluginManager().registerListener(this,this);
        startReceiver();
    }
    @Override public void onDisable() { running=false; if(socket!=null)socket.close(); fakeOnline.set(0); }

    @EventHandler(priority=127) public void onPing(ProxyPingEvent event) {
        ServerPing response=event.getResponse(); if(response==null)return;
        // Не использовать устаревшее значение, если Paper пропал без корректного выключения.
        int fake=System.currentTimeMillis()-lastUpdate>15000?0:fakeOnline.get();
        int total=ProxyServer.getInstance().getOnlineCount()+fake;
        ServerPing.Players players=response.getPlayers();
        if(players==null) players=new ServerPing.Players(total+1,total,null);
        else { players.setOnline(total); players.setMax(Math.max(players.getMax(),total+1)); }
        response.setPlayers(players); event.setResponse(response);
    }

    private void startReceiver() {
        Configuration c=readConfig(); secret=c.getString("secret","change-me"); int port=c.getInt("port",29175); String host=c.getString("bind-host","127.0.0.1");
        running=true;
        ProxyServer.getInstance().getScheduler().runAsync(this,()->{
            try {
                socket=new DatagramSocket(new InetSocketAddress(host,port));
                getLogger().info("Dynamic bot sync listening on "+host+":"+port);
                while(running){
                    byte[] data=new byte[256]; DatagramPacket packet=new DatagramPacket(data,data.length); socket.receive(packet);
                    String value=new String(packet.getData(),0,packet.getLength(),StandardCharsets.UTF_8);
                    String[] parts=value.split(":",3);
                    if(parts.length==3&&parts[0].equals(secret)){
                        try { fakeOnline.set(Math.max(0,Integer.parseInt(parts[1]))); lastUpdate=System.currentTimeMillis(); }
                        catch(NumberFormatException ignored){}
                    }
                }
            } catch(SocketException ex){if(running)getLogger().severe("Bot sync socket: "+ex.getMessage());}
            catch(IOException ex){getLogger().severe("Bot sync receive: "+ex.getMessage());}
        });
    }
    private void loadConfig() throws IOException {
        if(!getDataFolder().exists())getDataFolder().mkdirs(); File file=new File(getDataFolder(),"config.yml");
        if(!file.exists())try(InputStream in=getResourceAsStream("config.yml")){Files.copy(in,file.toPath());}
    }
    private Configuration readConfig(){try{return ConfigurationProvider.getProvider(YamlConfiguration.class).load(new File(getDataFolder(),"config.yml"));}catch(IOException ex){throw new RuntimeException(ex);}}
}
