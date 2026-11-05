package com.nep.auth.mapper;

import org.apache.ibatis.annotations.Mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.nep.auth.entity.AuthSession;

@Mapper
public interface AuthSessionMapper extends BaseMapper<AuthSession> {

}
