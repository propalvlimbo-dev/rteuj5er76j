package ru.elytrix.bots;

import java.io.File;
import java.sql.*;
import java.util.*;

final class PopulationDatabase implements AutoCloseable {
    private Connection connection;
    PopulationDatabase(File file){
        try{connection=DriverManager.getConnection("jdbc:sqlite:"+file.getAbsolutePath());try(Statement s=connection.createStatement()){s.executeUpdate("CREATE TABLE IF NOT EXISTS profiles(name TEXT PRIMARY KEY,last_quit INTEGER NOT NULL DEFAULT 0,cooldown_until INTEGER NOT NULL DEFAULT 0)");}}
        catch(SQLException ex){throw new IllegalStateException("SQLite init failed",ex);}
    }
    long cooldown(String name){try(PreparedStatement s=connection.prepareStatement("SELECT cooldown_until FROM profiles WHERE name=?")){s.setString(1,name);try(ResultSet r=s.executeQuery()){return r.next()?r.getLong(1):0;}}catch(SQLException ignored){return 0;}}
    void quit(String name,long cooldown){try(PreparedStatement s=connection.prepareStatement("INSERT INTO profiles(name,last_quit,cooldown_until) VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET last_quit=excluded.last_quit,cooldown_until=excluded.cooldown_until")){s.setString(1,name);s.setLong(2,System.currentTimeMillis());s.setLong(3,cooldown);s.executeUpdate();}catch(SQLException ignored){}}
    @Override public void close(){try{if(connection!=null)connection.close();}catch(SQLException ignored){}}
}
